"""Servicio de facturacion electronica SUNAT (API SUNAT / apisunat.pe).

Separado de services.py a proposito, igual que invoicing_models.py e
invoicing_schemas.py -- es un modulo que puede crecer solo (notas de
credito/debito, resumenes diarios, anulaciones) sin inflar el archivo de
servicios principal.

Diseno defensivo, mismo patron que app/integrations/wsp_notifications.py:
si el tenant no tiene `apisunat_token` configurado, el comprobante se
guarda igual en la base de datos como "draft" (nunca se pierde el intento,
nunca se rompe el flujo de la llamada/pedido) pero no se manda a SUNAT --
queda listo para reenviarse en cuanto se configure el token real.

Referencia de la API real (docs.apisunat.pe, leida en vivo):
  POST {base}/api/v3/documents            -- emitir boleta/factura/notas
  POST {base}/api/v3/status                -- consultar estado + URLs de PDF/XML/CDR
  base sandbox: https://sandbox.apisunat.pe
  base produccion: https://app.apisunat.pe
  Header: Authorization: Bearer {tenant.apisunat_token}
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.invoicing_models import Invoice, InvoiceItem, InvoiceSeries
from app.domain.invoicing_schemas import InvoiceFromOrderRequest, InvoiceItemOut, InvoiceOut
from app.domain.models import Customer, Order, OrderItem, Product, Tenant

logger = logging.getLogger(__name__)

_SANDBOX_BASE_URL = "https://sandbox.apisunat.pe"
_PRODUCTION_BASE_URL = "https://app.apisunat.pe"
_DOCUMENTS_PATH = "/api/v3/documents"
_TIMEOUT_SECONDS = 15.0

# Placeholder real que usa apisunat.pe para "boleta sin DNI" -- NO es un
# codigo de documento aparte, es DNI (tipo "1") con este numero fijo. Ver
# docs.apisunat.pe/facturacion/boleta-de-venta/boleta-sin-dni.
_SIN_DNI_TIPO = "1"
_SIN_DNI_NUMERO = "99999999"
_SIN_DNI_DENOMINACION = "CLIENTE VARIOS"

# codigo_tipo_afectacion_igv -> nombre_tributo que espera apisunat.pe (ver
# ejemplos reales: 10->IGV, 20->EXO, 21->GRA, 30->INA).
_TRIBUTO_POR_AFECTACION = {"10": "IGV", "20": "EXO", "21": "GRA", "30": "INA"}


class InvoicingError(Exception):
    """Igual que DomainError del resto del dominio, pero con nombre propio
    para no crear un import circular con services.py (que no necesita
    saber nada de facturacion)."""


class InvoicingService:
    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id

    # ---------- Series y correlativos ----------

    async def _allocate_number(self, document_type: str, serie: str) -> int:
        """Incrementa el correlativo de forma atomica (UPDATE...RETURNING,
        mismo patron que el descuento de stock en OrderService) para que dos
        emisiones concurrentes jamas repitan ni salten un numero -- SUNAT
        rechaza comprobantes con correlativo repetido o fuera de secuencia."""
        result = await self.session.execute(
            update(InvoiceSeries)
            .where(
                InvoiceSeries.tenant_id == self.tenant_id,
                InvoiceSeries.document_type == document_type,
                InvoiceSeries.serie == serie,
                InvoiceSeries.active.is_(True),
            )
            .values(next_number=InvoiceSeries.next_number + 1)
            .returning(InvoiceSeries.next_number)
        )
        row = result.first()
        if row is None:
            raise InvoicingError(
                f"No hay una serie activa '{serie}' para '{document_type}' en este tenant. "
                "Configúrala primero (ver InvoiceSeries)."
            )
        return row[0] - 1  # el next_number ya quedo incrementado; el numero usado es el anterior

    async def _default_serie(self, document_type: str) -> str:
        serie = await self.session.scalar(
            select(InvoiceSeries.serie).where(
                InvoiceSeries.tenant_id == self.tenant_id,
                InvoiceSeries.document_type == document_type,
                InvoiceSeries.active.is_(True),
            )
        )
        if not serie:
            raise InvoicingError(f"No hay ninguna serie activa configurada para '{document_type}'.")
        return serie

    # ---------- Resolucion del cliente (receptor) ----------

    @staticmethod
    def resolve_cliente(
        document_type: str,
        customer: Customer | None,
        override_tipo: str | None,
        override_numero: str | None,
        override_denominacion: str | None,
        override_direccion: str | None,
        fiscal_address: str | None = None,
    ) -> tuple[str, str, str, str]:
        """Devuelve (tipo_doc, numero_doc, denominacion, direccion) listos
        para el payload. Prioridad: lo que venga explicito en el request >
        lo que ya tenga el cliente en su ficha > placeholder de "boleta sin
        DNI" (solo valido para boleta, nunca para factura).

        `fiscal_address` es la direccion del LOCAL (Tenant.fiscal_address,
        ver invoicing_service.create_from_order) -- pedido explicito del
        negocio: si no hay direccion real del cliente (recojo en el local,
        o boleta sin ningun dato), el comprobante muestra la direccion del
        establecimiento en vez de quedar en blanco ("SIN DIRECCIÓN
        ESPECIFICADA" en el PDF de apisunat.pe, que se ve mal impreso)."""
        tipo = override_tipo or (customer.doc_type if customer else None)
        numero = override_numero or (customer.doc_number if customer else None)
        default_direccion = fiscal_address or "-"

        if document_type == "factura":
            if tipo != "6" or not numero or not numero.isdigit() or len(numero) != 11:
                raise InvoicingError(
                    "Para emitir factura el cliente necesita RUC valido (11 digitos, "
                    "cliente_tipo_de_documento='6'). No se puede facturar sin eso."
                )
            denominacion = override_denominacion or (customer.legal_name if customer else None) or (
                customer.name if customer else None
            )
            if not denominacion:
                raise InvoicingError("Falta la razón social del cliente para la factura.")
            direccion = override_direccion or (customer.address if customer else None) or default_direccion
            return tipo, numero, denominacion, direccion

        # boleta: el documento en ficha solo cuenta aca si es de PERSONA
        # (DNI/CE/pasaporte/cedula diplomatica). Bug real, visto en vivo: un
        # cliente que antes pidio factura queda con doc_type="6" (RUC)
        # guardado en su ficha -- una boleta posterior del mismo telefono
        # NO debe salir con ese RUC (RUC es cosa de factura), asi que un "6"
        # aca se descarta y cae al placeholder de "sin DNI" igual que si no
        # tuviera nada guardado.
        if tipo == "6":
            tipo, numero = None, None
        if not tipo or not numero:
            return _SIN_DNI_TIPO, _SIN_DNI_NUMERO, _SIN_DNI_DENOMINACION, default_direccion
        if tipo == "1" and (not numero.isdigit() or len(numero) != 8):
            raise InvoicingError("Para emitir boleta con DNI, el DNI debe tener exactamente 8 digitos.")

        denominacion = override_denominacion or (customer.name if customer else None) or (
            customer.legal_name if customer else None
        ) or _SIN_DNI_DENOMINACION
        direccion = override_direccion or (customer.address if customer else None) or default_direccion
        return tipo, numero, denominacion, direccion

    # ---------- Lineas de detalle ----------

    @staticmethod
    def _line_from_order_item(
        item: OrderItem, product: Product | None, igv_override_pct: float | None = None
    ) -> dict:
        """Convierte una linea de pedido en los campos SUNAT de una linea de
        comprobante. `item.unit_price` (heredado de Product.price al
        confirmar el pedido) ya incluye IGV -- se calcula el valor sin IGV
        a partir de la tasa real del producto, salvo que la afectacion sea
        gratuita/exonerada/inafecta, donde el valor de venta SI se declara
        pero sin IGV (porcentaje_igv=0 en el payload, como muestran los
        ejemplos reales de apisunat.pe).

        `igv_override_pct` sirve para el caso "Boleta simple 10.5%" (ver
        InvoiceFromOrderRequest.porcentaje_igv): todo el comprobante usa esa
        tasa en vez de la del producto, SOLO para lineas gravadas -- items
        exonerados/gratuitos/inafectos no llevan tasa de todos modos."""
        igv_code = product.igv_affectation_code if product else "10"
        igv_pct = igv_override_pct if igv_override_pct is not None else (product.igv_percentage if product else 18.0)
        tributo = product.igv_tribute_name if product else _TRIBUTO_POR_AFECTACION.get(igv_code, "IGV")
        unidad = product.unidad_medida if product else "NIU"
        codigo_interno = product.sku if product else None

        price_with_igv = item.unit_price
        if igv_code == "10":
            valor_unitario = round(price_with_igv / (1 + igv_pct / 100), 6)
            porcentaje_igv_payload = igv_pct
        else:
            # exonerado/gratuito/inafecto: sin componente de IGV en el payload.
            valor_unitario = round(price_with_igv, 6)
            porcentaje_igv_payload = 0.0

        return {
            "unidad_de_medida": unidad,
            "codigo_interno": codigo_interno,
            "descripcion": (product.name if product else item.notes) or "Item",
            "cantidad": item.quantity,
            "valor_unitario": valor_unitario,
            "precio_unitario": round(price_with_igv, 6),
            "porcentaje_igv": porcentaje_igv_payload,
            "codigo_tipo_afectacion_igv": igv_code,
            "nombre_tributo": tributo,
            "product_id": product.id if product else None,
        }

    # ---------- Crear comprobante a partir de un pedido ----------

    async def create_from_order(self, payload: InvoiceFromOrderRequest) -> InvoiceOut:
        order = await self.session.scalar(
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.product), selectinload(Order.customer))
            .where(Order.tenant_id == self.tenant_id, Order.id == payload.order_id)
        )
        if not order:
            raise InvoicingError("Pedido no encontrado.")
        if not order.items:
            raise InvoicingError("El pedido no tiene items, no se puede facturar.")

        # Evita doble emision accidental: un pedido ya facturado (y no
        # anulado) no se vuelve a facturar solo -- para corregir algo se usa
        # nota de credito/debito (ver invoicing_schemas.CreditNoteRequest),
        # no una segunda emision del mismo tipo.
        existing = await self.session.scalar(
            select(Invoice).where(
                Invoice.tenant_id == self.tenant_id,
                Invoice.order_id == order.id,
                Invoice.document_type == payload.document_type,
                Invoice.sunat_status != "voided",
            )
        )
        if existing:
            raise InvoicingError(
                f"El pedido #{order.id} ya tiene {payload.document_type} "
                f"{existing.serie}-{existing.numero} ({existing.sunat_status})."
            )

        tenant = await self.session.get(Tenant, self.tenant_id)
        tipo_doc, numero_doc, denominacion, direccion = self.resolve_cliente(
            payload.document_type,
            order.customer,
            payload.cliente_tipo_doc,
            payload.cliente_numero_doc,
            payload.cliente_denominacion,
            payload.cliente_direccion,
            fiscal_address=tenant.fiscal_address if tenant else None,
        )

        # porcentaje_igv del request es una eleccion a nivel de todo el
        # comprobante (18% estandar vs 10.5%, ver "Boleta simple 10.5%"),
        # no algo por producto -- se aplica igual a todas las lineas
        # gravadas del pedido.
        lines = [
            self._line_from_order_item(item, item.product, igv_override_pct=payload.porcentaje_igv)
            for item in order.items
        ]

        total_gravada = sum(
            round(line["valor_unitario"] * line["cantidad"], 2)
            for line in lines
            if line["codigo_tipo_afectacion_igv"] == "10"
        )
        total_exonerada = sum(
            round(line["valor_unitario"] * line["cantidad"], 2)
            for line in lines
            if line["codigo_tipo_afectacion_igv"] == "20"
        )
        total_gratuita = sum(
            round(line["valor_unitario"] * line["cantidad"], 2)
            for line in lines
            if line["codigo_tipo_afectacion_igv"] == "21"
        )
        # IGV real: diferencia entre lo cobrado (precio con IGV incluido, ya
        # sumado en order.total) y la base gravada -- mas simple y exacto
        # que resumar tasas por linea con redondeos propios.
        gravada_con_igv = sum(
            item.unit_price * item.quantity for item, line in zip(order.items, lines, strict=True)
            if line["codigo_tipo_afectacion_igv"] == "10"
        )
        total_igv = round(gravada_con_igv - total_gravada, 2)

        serie = await self._default_serie(payload.document_type)
        numero = await self._allocate_number(payload.document_type, serie)

        now = datetime.now(UTC)
        invoice = Invoice(
            tenant_id=self.tenant_id,
            order_id=order.id,
            document_type=payload.document_type,
            serie=serie,
            numero=numero,
            fecha_emision=now.date(),
            hora_emision=now.strftime("%H:%M:%S"),
            fecha_vencimiento=payload.fecha_vencimiento,
            moneda="PEN",
            tipo_operacion="0101",
            observacion=payload.observacion,
            cliente_tipo_doc=tipo_doc,
            cliente_numero_doc=numero_doc,
            cliente_denominacion=denominacion,
            cliente_direccion=direccion,
            total_gravada=total_gravada or None,
            total_igv=total_igv or None,
            total_exonerada=total_exonerada or None,
            total_gratuita=total_gratuita or None,
            total=round(sum(item.unit_price * item.quantity for item in order.items), 2),
            sunat_status="draft",
        )
        self.session.add(invoice)
        await self.session.flush()

        for line in lines:
            self.session.add(
                InvoiceItem(
                    tenant_id=self.tenant_id,
                    invoice_id=invoice.id,
                    product_id=line["product_id"],
                    unidad_medida=line["unidad_de_medida"],
                    codigo_interno=line["codigo_interno"],
                    descripcion=line["descripcion"],
                    cantidad=line["cantidad"],
                    valor_unitario=line["valor_unitario"],
                    precio_unitario=line["precio_unitario"],
                    porcentaje_igv=line["porcentaje_igv"],
                    codigo_tipo_afectacion_igv=line["codigo_tipo_afectacion_igv"],
                    nombre_tributo=line["nombre_tributo"],
                )
            )
        await self.session.commit()

        await self._send_to_sunat(invoice.id)
        return await self.get(invoice.id)

    # ---------- Envio a API SUNAT ----------

    def build_payload(self, invoice: Invoice, items: list[InvoiceItem]) -> dict:
        payload: dict = {
            "documento": invoice.document_type,
            "serie": invoice.serie,
            "numero": invoice.numero,
            "fecha_de_emision": invoice.fecha_emision.isoformat(),
            "moneda": invoice.moneda,
            "tipo_operacion": invoice.tipo_operacion,
            "cliente_tipo_de_documento": invoice.cliente_tipo_doc,
            "cliente_numero_de_documento": invoice.cliente_numero_doc,
            "cliente_denominacion": invoice.cliente_denominacion,
            "cliente_direccion": invoice.cliente_direccion,
            "items": [
                {
                    "unidad_de_medida": item.unidad_medida,
                    "codigo_interno": item.codigo_interno,
                    "descripcion": item.descripcion,
                    "cantidad": str(item.cantidad),
                    "valor_unitario": str(item.valor_unitario),
                    "porcentaje_igv": str(item.porcentaje_igv),
                    "codigo_tipo_afectacion_igv": item.codigo_tipo_afectacion_igv,
                    "nombre_tributo": item.nombre_tributo,
                }
                for item in items
            ],
            "total": str(invoice.total),
        }
        if invoice.hora_emision:
            payload["hora_de_emision"] = invoice.hora_emision
        if invoice.observacion:
            payload["observacion"] = invoice.observacion
        if invoice.fecha_vencimiento:
            payload["fecha_de_vencimiento"] = invoice.fecha_vencimiento.isoformat()
        return payload

    async def _send_to_sunat(self, invoice_id: int) -> None:
        """Manda el comprobante ya guardado como draft a API SUNAT. Si el
        tenant no tiene token configurado, lo deja en draft con un mensaje
        explicativo -- a diferencia de wsp_notifications (que es un aviso de
        cortesia, fire-and-forget), esto SI se espera (await directo desde
        create_from_order) porque quien pidio el comprobante necesita saber
        de una si SUNAT lo acepto o no, no solo que quedo guardado."""
        invoice = await self.session.get(Invoice, invoice_id)
        items = (
            await self.session.execute(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice_id))
        ).scalars().all()
        tenant = await self.session.get(Tenant, self.tenant_id)

        if not tenant or not tenant.apisunat_token:
            invoice.sunat_status = "draft"
            invoice.sunat_message = (
                "apisunat_token no configurado para este negocio -- comprobante guardado, "
                "no enviado a SUNAT todavia."
            )
            await self.session.commit()
            return

        base_url = _PRODUCTION_BASE_URL if tenant.apisunat_environment == "production" else _SANDBOX_BASE_URL
        payload = self.build_payload(invoice, items)

        invoice.sunat_status = "sent"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    f"{base_url}{_DOCUMENTS_PATH}",
                    json=payload,
                    headers={"Authorization": f"Bearer {tenant.apisunat_token}"},
                )
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if resp.status_code == 200 and data.get("success"):
                result = data.get("payload") or {}
                invoice.sunat_status = _map_estado(result.get("estado"))
                invoice.sunat_hash = result.get("hash")
                invoice.sunat_xml_url = result.get("xml")
                invoice.sunat_cdr_url = result.get("cdr")
                pdf = result.get("pdf") or {}
                invoice.sunat_pdf_ticket_url = pdf.get("ticket")
                invoice.sunat_pdf_a4_url = pdf.get("a4")
                invoice.sunat_message = data.get("message")
            else:
                invoice.sunat_status = "rejected"
                invoice.sunat_message = data.get("message") or resp.text[:500]
                logger.warning(
                    "apisunat.pe: comprobante rechazado invoice_id=%s status_code=%s body=%s",
                    invoice.id, resp.status_code, resp.text[:500],
                )
        except Exception as exc:
            invoice.sunat_status = "rejected"
            invoice.sunat_message = f"Error de red/conexion con apisunat.pe: {exc}"
            logger.exception("apisunat.pe: fallo al enviar comprobante invoice_id=%s", invoice.id)

        await self.session.commit()

    # ---------- Lectura ----------

    async def get(self, invoice_id: int) -> InvoiceOut:
        invoice = await self.session.scalar(
            select(Invoice)
            .options(selectinload(Invoice.items))
            .where(Invoice.tenant_id == self.tenant_id, Invoice.id == invoice_id)
        )
        if not invoice:
            raise InvoicingError("Comprobante no encontrado.")
        return _to_out(invoice)

    async def get_by_order(self, order_id: int) -> InvoiceOut | None:
        """Para el panel de Llamadas (ver app/api/v1/conversations.py):
        mostrar de una si el pedido de esta llamada ya tiene su boleta/
        factura, y en que estado quedo. None si todavia no se emitio nada
        (o si fallo antes de crear el borrador -- ej. sin serie activa)."""
        invoice = await self.session.scalar(
            select(Invoice)
            .options(selectinload(Invoice.items))
            .where(Invoice.tenant_id == self.tenant_id, Invoice.order_id == order_id)
            .order_by(Invoice.id.desc())
        )
        return _to_out(invoice) if invoice else None

    async def list_recent(self, limit: int = 50) -> list[InvoiceOut]:
        invoices = (
            await self.session.execute(
                select(Invoice)
                .options(selectinload(Invoice.items))
                .where(Invoice.tenant_id == self.tenant_id)
                .order_by(Invoice.id.desc())
                .limit(limit)
            )
        ).scalars().all()
        return [_to_out(invoice) for invoice in invoices]


def _map_estado(estado: str | None) -> str:
    return {"ACEPTADO": "accepted", "PENDIENTE": "pending", "RECHAZADO": "rejected"}.get(
        (estado or "").upper(), "sent"
    )


def _to_out(invoice: Invoice) -> InvoiceOut:
    return InvoiceOut(
        id=invoice.id,
        order_id=invoice.order_id,
        document_type=invoice.document_type,
        serie=invoice.serie,
        numero=invoice.numero,
        fecha_emision=invoice.fecha_emision,
        hora_emision=invoice.hora_emision,
        fecha_vencimiento=invoice.fecha_vencimiento,
        moneda=invoice.moneda,
        tipo_operacion=invoice.tipo_operacion,
        observacion=invoice.observacion,
        cliente_tipo_doc=invoice.cliente_tipo_doc,
        cliente_numero_doc=invoice.cliente_numero_doc,
        cliente_denominacion=invoice.cliente_denominacion,
        cliente_direccion=invoice.cliente_direccion,
        total_gravada=invoice.total_gravada,
        total_igv=invoice.total_igv,
        total_exonerada=invoice.total_exonerada,
        total=invoice.total,
        nota_codigo_tipo=invoice.nota_codigo_tipo,
        nota_motivo=invoice.nota_motivo,
        documento_afectado_id=invoice.documento_afectado_id,
        sunat_status=invoice.sunat_status,
        sunat_hash=invoice.sunat_hash,
        sunat_message=invoice.sunat_message,
        sunat_xml_url=invoice.sunat_xml_url,
        sunat_cdr_url=invoice.sunat_cdr_url,
        sunat_pdf_ticket_url=invoice.sunat_pdf_ticket_url,
        sunat_pdf_a4_url=invoice.sunat_pdf_a4_url,
        items=[
            InvoiceItemOut(
                id=item.id,
                product_id=item.product_id,
                unidad_medida=item.unidad_medida,
                codigo_interno=item.codigo_interno,
                descripcion=item.descripcion,
                cantidad=item.cantidad,
                valor_unitario=item.valor_unitario,
                precio_unitario=item.precio_unitario,
                porcentaje_igv=item.porcentaje_igv,
                codigo_tipo_afectacion_igv=item.codigo_tipo_afectacion_igv,
            )
            for item in invoice.items
        ],
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
    )
