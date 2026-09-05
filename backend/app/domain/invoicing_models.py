"""Modelos SQLAlchemy para facturación electrónica SUNAT.

Módulo independiente: no modifica tablas existentes. Se conecta al sistema
vía FK a orders.id y customers, y hereda los mismos mixins (TenantScoped,
Timestamp) que el resto del dominio.

Comprobantes soportados:
  - Factura simple (F001)
  - Factura al crédito (F001 con fecha_vencimiento)
  - Boleta simple 18% (B001)
  - Boleta sin DNI (B001, cliente_tipo_doc="-")
  - Nota de crédito (FC01 / BC01)
  - Nota de débito (FD01 / BD01)
"""

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, TenantScopedMixin, TimestampMixin


class InvoiceSeries(Base, TenantScopedMixin, TimestampMixin):
    """Control de series y correlativos por tenant.

    Cada tenant puede tener múltiples series activas (F001 para facturas,
    B001 para boletas, etc). El correlativo se incrementa atómicamente
    en cada emisión con SELECT ... FOR UPDATE para evitar huecos o
    duplicados bajo concurrencia.
    """

    __tablename__ = "invoice_series"
    __table_args__ = (UniqueConstraint("tenant_id", "document_type", "serie"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_type: Mapped[str] = mapped_column(String(20))  # factura | boleta | nota_credito | nota_debito
    serie: Mapped[str] = mapped_column(String(4))  # F001, B001, FC01, BC01
    next_number: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(default=True)


class Invoice(Base, TenantScopedMixin, TimestampMixin):
    """Comprobante electrónico emitido (o en borrador).

    Mapea 1:1 al JSON que se envía a POST /api/v3/documents de API SUNAT.
    El campo `sunat_status` rastrea el ciclo de vida completo:
      draft -> sent -> accepted | pending | rejected | voided
    """

    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("tenant_id", "document_type", "serie", "numero"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)

    # --- Identificación del comprobante ---
    document_type: Mapped[str] = mapped_column(String(20))  # factura | boleta | nota_credito | nota_debito
    serie: Mapped[str] = mapped_column(String(4))
    numero: Mapped[int] = mapped_column(Integer)
    fecha_emision: Mapped[date] = mapped_column(Date)
    hora_emision: Mapped[str | None] = mapped_column(String(8))  # HH:MM:SS
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date)  # obligatorio para credito
    moneda: Mapped[str] = mapped_column(String(3), default="PEN")
    tipo_operacion: Mapped[str] = mapped_column(String(4), default="0101")  # 0101 = venta interna
    observacion: Mapped[str | None] = mapped_column(Text)

    # --- Datos del receptor (cliente), catalogo 06 SUNAT ---
    # "0"=Sin documento, "1"=DNI, "4"=CE, "6"=RUC, "7"=Pasaporte, "A"=Cedula
    # diplomatica. Una boleta "sin DNI" NO usa un tipo especial: sigue la
    # convencion real de apisunat.pe, tipo_doc="1" + numero_doc="99999999"
    # (ver invoicing_services.py, _resolve_cliente).
    cliente_tipo_doc: Mapped[str] = mapped_column(String(4))
    cliente_numero_doc: Mapped[str | None] = mapped_column(String(20))
    cliente_denominacion: Mapped[str] = mapped_column(String(200))
    cliente_direccion: Mapped[str | None] = mapped_column(String(300))

    # --- Montos ---
    total_gravada: Mapped[float | None] = mapped_column(Float)  # base imponible
    total_igv: Mapped[float | None] = mapped_column(Float)  # IGV calculado
    total_exonerada: Mapped[float | None] = mapped_column(Float)
    total_gratuita: Mapped[float | None] = mapped_column(Float)
    total: Mapped[float] = mapped_column(Float)

    # --- Notas de crédito / débito ---
    nota_codigo_tipo: Mapped[str | None] = mapped_column(String(2))  # "01"=anulación, "02"=aumento
    nota_motivo: Mapped[str | None] = mapped_column(String(200))
    documento_afectado_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))

    # --- Estado SUNAT ---
    sunat_status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|sent|accepted|pending|rejected|voided
    sunat_hash: Mapped[str | None] = mapped_column(String(100))
    sunat_message: Mapped[str | None] = mapped_column(Text)
    sunat_xml_url: Mapped[str | None] = mapped_column(String(500))
    sunat_cdr_url: Mapped[str | None] = mapped_column(String(500))
    sunat_pdf_ticket_url: Mapped[str | None] = mapped_column(String(500))
    sunat_pdf_a4_url: Mapped[str | None] = mapped_column(String(500))

    # --- Relaciones ---
    items: Mapped[list["InvoiceItem"]] = relationship(cascade="all, delete-orphan", back_populates="invoice")
    documento_afectado: Mapped["Invoice | None"] = relationship(remote_side="Invoice.id")


class InvoiceItem(Base, TenantScopedMixin, TimestampMixin):
    """Línea de detalle del comprobante electrónico.

    Mapea al array "items" del JSON de API SUNAT. Cada ítem lleva su
    propio cálculo de IGV (puede variar entre gravado/exonerado/inafecto
    dentro del mismo comprobante).
    """

    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))

    # --- Campos que mapean al JSON de API SUNAT ---
    unidad_medida: Mapped[str] = mapped_column(String(5), default="NIU")  # NIU=bienes, ZZ=servicios
    codigo_interno: Mapped[str | None] = mapped_column(String(30))  # SKU del producto
    descripcion: Mapped[str] = mapped_column(String(300))
    cantidad: Mapped[float] = mapped_column(Float)
    valor_unitario: Mapped[float] = mapped_column(Float)  # precio sin IGV (6 decimales recomendado)
    precio_unitario: Mapped[float | None] = mapped_column(Float)  # precio con IGV incluido
    porcentaje_igv: Mapped[float] = mapped_column(Float, default=18.0)
    codigo_tipo_afectacion_igv: Mapped[str] = mapped_column(String(2), default="10")  # 10=gravado, 20=exonerado, 30=inafecto
    nombre_tributo: Mapped[str] = mapped_column(String(10), default="IGV")

    # --- Relaciones ---
    invoice: Mapped["Invoice"] = relationship(back_populates="items")
