"""Facturacion electronica SUNAT: construccion del payload, resolucion del
cliente (DNI/RUC/sin documento), calculo de IGV por linea, correlativos sin
huecos, y las reglas de negocio minimas (factura exige RUC, un pedido no se
factura dos veces). Nunca pega a la red real -- sin apisunat_token
configurado en el tenant (el caso por defecto en tests, ver conftest.py y
seed_demo_data), el comprobante se guarda como "draft" y ahi se queda."""

import pytest
from sqlalchemy import select

from app.domain.invoicing_models import Invoice, InvoiceItem, InvoiceSeries
from app.domain.invoicing_schemas import InvoiceFromOrderRequest
from app.domain.invoicing_services import InvoicingError, InvoicingService
from app.domain.models import InventoryItem, Product
from app.domain.schemas import CustomerCreate, CustomerUpdate, OrderCreate, OrderItemIn
from app.domain.services import CustomerService, OrderService
from app.infrastructure.config import settings
from app.infrastructure.db.session import AsyncSessionLocal, init_db
from app.infrastructure.seed import seed_demo_data


@pytest.fixture(autouse=True)
async def demo_db():
    await init_db()
    await seed_demo_data()


async def _make_order(session, customer_id: int | None = None) -> int:
    products = await session.execute(select(Product).where(Product.sku == "HB-CLA"))
    product = products.scalars().first()
    order = await OrderService(session, settings.default_tenant_id).create_confirmed_order(
        OrderCreate(customer_id=customer_id, items=[OrderItemIn(product_id=product.id, quantity=2)])
    )
    return order.id


async def _make_gratuito_product(session) -> Product:
    product = Product(
        tenant_id=settings.default_tenant_id,
        sku="PROMO-GRATIS",
        name="Postre de regalo",
        price=0.0,
        category="promocion",
        igv_affectation_code="21",
        igv_percentage=0.0,
        igv_tribute_name="GRA",
    )
    session.add(product)
    await session.flush()
    session.add(InventoryItem(tenant_id=settings.default_tenant_id, product_id=product.id, quantity=999, reserved=0))
    await session.commit()
    return product


@pytest.mark.asyncio
async def test_boleta_without_customer_doc_uses_sin_dni_placeholder():
    async with AsyncSessionLocal() as session:
        customer_svc = CustomerService(session, settings.default_tenant_id)
        customer = await customer_svc.get_or_create(CustomerCreate(name="Carlos", phone="+51900111222"))
        await session.commit()

        order_id = await _make_order(session, customer.id)
        invoice = await InvoicingService(session, settings.default_tenant_id).create_from_order(
            InvoiceFromOrderRequest(order_id=order_id, document_type="boleta")
        )

        assert invoice.cliente_tipo_doc == "1"
        assert invoice.cliente_numero_doc == "99999999"
        assert invoice.cliente_denominacion == "CLIENTE VARIOS"
        assert invoice.serie == "B001"
        assert invoice.numero == 1
        # Sin apisunat_token configurado, se queda como draft -- nunca intenta red.
        assert invoice.sunat_status == "draft"
        assert "apisunat_token" in (invoice.sunat_message or "")


@pytest.mark.asyncio
async def test_boleta_with_dni_uses_customer_data():
    async with AsyncSessionLocal() as session:
        customer_svc = CustomerService(session, settings.default_tenant_id)
        customer = await customer_svc.get_or_create(CustomerCreate(name="Maria Lopez", phone="+51900111333"))
        await session.commit()
        await customer_svc.update(customer.id, CustomerUpdate(doc_type="1", doc_number="75413811"))

        order_id = await _make_order(session, customer.id)
        invoice = await InvoicingService(session, settings.default_tenant_id).create_from_order(
            InvoiceFromOrderRequest(order_id=order_id, document_type="boleta")
        )

        assert invoice.cliente_tipo_doc == "1"
        assert invoice.cliente_numero_doc == "75413811"
        assert invoice.cliente_denominacion == "Maria Lopez"


@pytest.mark.asyncio
async def test_factura_requires_ruc():
    async with AsyncSessionLocal() as session:
        customer_svc = CustomerService(session, settings.default_tenant_id)
        customer = await customer_svc.get_or_create(CustomerCreate(name="Sin RUC", phone="+51900111444"))
        await session.commit()

        order_id = await _make_order(session, customer.id)
        with pytest.raises(InvoicingError, match="RUC"):
            await InvoicingService(session, settings.default_tenant_id).create_from_order(
                InvoiceFromOrderRequest(order_id=order_id, document_type="factura")
            )


@pytest.mark.asyncio
async def test_factura_with_ruc_uses_legal_name_and_f001_series():
    async with AsyncSessionLocal() as session:
        customer_svc = CustomerService(session, settings.default_tenant_id)
        customer = await customer_svc.get_or_create(CustomerCreate(name="Contacto", phone="+51900111555"))
        await session.commit()
        await customer_svc.update(
            customer.id,
            CustomerUpdate(doc_type="6", doc_number="20123456789", legal_name="EMPRESA DE SERVICIOS S.A.C"),
        )

        order_id = await _make_order(session, customer.id)
        invoice = await InvoicingService(session, settings.default_tenant_id).create_from_order(
            InvoiceFromOrderRequest(order_id=order_id, document_type="factura")
        )

        assert invoice.cliente_tipo_doc == "6"
        assert invoice.cliente_numero_doc == "20123456789"
        assert invoice.cliente_denominacion == "EMPRESA DE SERVICIOS S.A.C"
        assert invoice.serie == "F001"


@pytest.mark.asyncio
async def test_boleta_18_percent_igv_line_math():
    async with AsyncSessionLocal() as session:
        order_id = await _make_order(session)  # Hamburguesa Clasica x2, S/12.90 c/u con IGV
        invoice = await InvoicingService(session, settings.default_tenant_id).create_from_order(
            InvoiceFromOrderRequest(order_id=order_id, document_type="boleta")
        )

        assert len(invoice.items) == 1
        item = invoice.items[0]
        assert item.codigo_tipo_afectacion_igv == "10"
        assert item.porcentaje_igv == 18.0
        # 12.90 / 1.18 = 10.932203...
        assert item.valor_unitario == pytest.approx(10.932203, abs=1e-4)
        assert invoice.total == pytest.approx(25.80, abs=1e-2)
        assert invoice.total_igv == pytest.approx(25.80 - 2 * item.valor_unitario, abs=1e-2)


@pytest.mark.asyncio
async def test_boleta_10_5_percent_override_recalculates_valor_unitario():
    async with AsyncSessionLocal() as session:
        order_id = await _make_order(session)
        invoice = await InvoicingService(session, settings.default_tenant_id).create_from_order(
            InvoiceFromOrderRequest(order_id=order_id, document_type="boleta", porcentaje_igv=10.5)
        )
        item = invoice.items[0]
        assert item.porcentaje_igv == 10.5
        # 12.90 / 1.105 = 11.674208...
        assert item.valor_unitario == pytest.approx(11.674208, abs=1e-4)


@pytest.mark.asyncio
async def test_gratuito_item_has_no_igv_component():
    async with AsyncSessionLocal() as session:
        product = await _make_gratuito_product(session)
        order = await OrderService(session, settings.default_tenant_id).create_confirmed_order(
            OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=1)])
        )
        invoice = await InvoicingService(session, settings.default_tenant_id).create_from_order(
            InvoiceFromOrderRequest(order_id=order.id, document_type="boleta")
        )
        item = invoice.items[0]
        assert item.codigo_tipo_afectacion_igv == "21"
        assert item.porcentaje_igv == 0
        assert item.valor_unitario == 0


@pytest.mark.asyncio
async def test_series_increment_without_gaps_across_multiple_orders():
    async with AsyncSessionLocal() as session:
        svc = InvoicingService(session, settings.default_tenant_id)
        numbers = []
        for _ in range(3):
            order_id = await _make_order(session)
            invoice = await svc.create_from_order(
                InvoiceFromOrderRequest(order_id=order_id, document_type="boleta")
            )
            numbers.append(invoice.numero)
        # No arrancan necesariamente en 1 -- este archivo de tests comparte
        # la misma DB (y el mismo contador de serie B001) con los tests
        # anteriores dentro de la misma corrida de pytest (mismo patron que
        # el resto de la suite: unicidad relativa, no valores absolutos).
        assert numbers == [numbers[0], numbers[0] + 1, numbers[0] + 2]

        series = await session.scalar(
            select(InvoiceSeries).where(
                InvoiceSeries.tenant_id == settings.default_tenant_id,
                InvoiceSeries.document_type == "boleta",
                InvoiceSeries.serie == "B001",
            )
        )
        assert series.next_number == numbers[-1] + 1


@pytest.mark.asyncio
async def test_cannot_invoice_same_order_twice_with_same_document_type():
    async with AsyncSessionLocal() as session:
        svc = InvoicingService(session, settings.default_tenant_id)
        order_id = await _make_order(session)
        await svc.create_from_order(InvoiceFromOrderRequest(order_id=order_id, document_type="boleta"))

        with pytest.raises(InvoicingError, match="ya tiene"):
            await svc.create_from_order(InvoiceFromOrderRequest(order_id=order_id, document_type="boleta"))


@pytest.mark.asyncio
async def test_build_payload_matches_apisunat_field_names():
    async with AsyncSessionLocal() as session:
        order_id = await _make_order(session)
        svc = InvoicingService(session, settings.default_tenant_id)
        invoice_out = await svc.create_from_order(
            InvoiceFromOrderRequest(order_id=order_id, document_type="boleta")
        )

        invoice_row = await session.get(Invoice, invoice_out.id)
        items = (
            await session.execute(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice_row.id))
        ).scalars().all()
        payload = svc.build_payload(invoice_row, items)

        assert payload["documento"] == "boleta"
        assert payload["serie"] == "B001"
        assert isinstance(payload["numero"], int)
        assert payload["moneda"] == "PEN"
        assert payload["tipo_operacion"] == "0101"
        assert payload["cliente_tipo_de_documento"] == "1"
        assert payload["cliente_numero_de_documento"] == "99999999"
        assert "fecha_de_emision" in payload
        line = payload["items"][0]
        assert set(line) == {
            "unidad_de_medida", "codigo_interno", "descripcion", "cantidad",
            "valor_unitario", "porcentaje_igv", "codigo_tipo_afectacion_igv", "nombre_tributo",
        }
        assert line["unidad_de_medida"] == "NIU"
