"""Schemas Pydantic para el módulo de facturación electrónica.

Separados del schemas.py principal para mantener el módulo independiente.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field

# ---------- REQUEST SCHEMAS ----------

class InvoiceItemIn(BaseModel):
    """Línea de producto para crear un comprobante."""
    product_id: int | None = None
    descripcion: str
    cantidad: float = Field(gt=0)
    valor_unitario: float = Field(gt=0, description="Precio sin IGV")
    unidad_medida: str = "NIU"  # NIU=bienes, ZZ=servicios
    codigo_interno: str | None = None
    porcentaje_igv: float = 18.0
    codigo_tipo_afectacion_igv: str = "10"  # 10=gravado, 20=exonerado, 30=inafecto


class InvoiceFromOrderRequest(BaseModel):
    """Crear comprobante a partir de una orden existente."""
    order_id: int
    document_type: str = Field(pattern="^(factura|boleta)$")
    # Datos del receptor -- opcionales si el cliente ya los tiene en BD
    cliente_tipo_doc: str | None = None  # "1"=DNI, "6"=RUC, "-"=sin doc
    cliente_numero_doc: str | None = None
    cliente_denominacion: str | None = None
    cliente_direccion: str | None = None
    # Factura al crédito
    fecha_vencimiento: date | None = None
    observacion: str | None = None
    # IGV override (default 18%)
    porcentaje_igv: float = 18.0


class InvoiceCreateDirect(BaseModel):
    """Crear comprobante sin orden asociada (uso manual/directo)."""
    document_type: str = Field(pattern="^(factura|boleta)$")
    cliente_tipo_doc: str
    cliente_numero_doc: str | None = None
    cliente_denominacion: str
    cliente_direccion: str | None = None
    moneda: str = "PEN"
    observacion: str | None = None
    fecha_vencimiento: date | None = None
    items: list[InvoiceItemIn]


class InvoiceVoidRequest(BaseModel):
    """Anular un comprobante emitido."""
    motivo: str = "ANULACIÓN DE OPERACIÓN"


class CreditNoteRequest(BaseModel):
    """Crear nota de crédito contra un comprobante existente."""
    invoice_id: int  # comprobante a afectar
    codigo_tipo: str = "01"  # 01=anulación, 02=corrección
    motivo: str = "Anulación de la operación"
    items: list[InvoiceItemIn] | None = None  # si None, copia los del original


# ---------- RESPONSE SCHEMAS ----------

class InvoiceItemOut(BaseModel):
    id: int
    product_id: int | None
    unidad_medida: str
    codigo_interno: str | None
    descripcion: str
    cantidad: float
    valor_unitario: float
    precio_unitario: float | None
    porcentaje_igv: float
    codigo_tipo_afectacion_igv: str


class InvoiceOut(BaseModel):
    id: int
    order_id: int | None
    document_type: str
    serie: str
    numero: int
    fecha_emision: date
    hora_emision: str | None
    fecha_vencimiento: date | None
    moneda: str
    tipo_operacion: str
    observacion: str | None
    # Receptor
    cliente_tipo_doc: str
    cliente_numero_doc: str | None
    cliente_denominacion: str
    cliente_direccion: str | None
    # Montos
    total_gravada: float | None
    total_igv: float | None
    total_exonerada: float | None
    total: float
    # Notas
    nota_codigo_tipo: str | None = None
    nota_motivo: str | None = None
    documento_afectado_id: int | None = None
    # Estado SUNAT
    sunat_status: str
    sunat_hash: str | None = None
    sunat_message: str | None = None
    sunat_xml_url: str | None = None
    sunat_cdr_url: str | None = None
    sunat_pdf_ticket_url: str | None = None
    sunat_pdf_a4_url: str | None = None
    # Items
    items: list[InvoiceItemOut] = []
    # Timestamps
    created_at: datetime
    updated_at: datetime


class InvoiceListOut(BaseModel):
    """Resumen para listado (sin items detallados)."""
    id: int
    order_id: int | None
    document_type: str
    serie: str
    numero: int
    fecha_emision: date
    cliente_denominacion: str
    total: float
    sunat_status: str
    created_at: datetime


class InvoiceSeriesOut(BaseModel):
    id: int
    document_type: str
    serie: str
    next_number: int
    active: bool
