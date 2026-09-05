from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.invoicing_schemas import InvoiceOut


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    description: str | None
    price: float
    category: str
    stock_available: int
    # --- Campos SUNAT (ver invoicing_services.py) ---
    unidad_medida: str = "NIU"  # catalogo 03: NIU=bienes, ZZ=servicios
    igv_affectation_code: str = "10"  # catalogo 07: 10=gravado, 20=exonerado, 21=gratuito, 30=inafecto
    igv_percentage: float = 18.0
    igv_tribute_name: str = "IGV"


class CustomerCreate(BaseModel):
    name: str
    phone: str | None = None
    address: str | None = None
    notes: str | None = None
    # --- Datos fiscales (catalogo 06 SUNAT), opcionales -- ver
    # invoicing_services.resolve_cliente para como se usan al facturar ---
    doc_type: str | None = None  # "1"=DNI, "6"=RUC, "4"=CE, "7"=Pasaporte, "0"=Sin doc
    doc_number: str | None = None
    legal_name: str | None = None  # razon social, solo si doc_type="6"


class CustomerOut(CustomerCreate):
    id: int


class CustomerUpdate(BaseModel):
    # Todo opcional: PATCH solo toca lo que venga presente. name explicitamente
    # puede venir vacio en el JSON (validado como "no vacio" en el endpoint,
    # no aca) para no confundir "no lo mande" con "lo mande vacio".
    name: str | None = None
    phone: str | None = None
    address: str | None = None
    notes: str | None = None
    doc_type: str | None = None
    doc_number: str | None = None
    legal_name: str | None = None


class OrderItemIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    notes: str | None = None


class OrderCreate(BaseModel):
    customer_id: int | None = None
    conversation_id: str | None = None
    requested_time: str | None = None
    fulfillment_type: str | None = None
    delivery_address: str | None = None
    payment_method: str | None = None
    items: list[OrderItemIn]


class OrderItemOut(BaseModel):
    product_id: int
    product_name: str
    quantity: int
    unit_price: float
    notes: str | None


class OrderOut(BaseModel):
    id: int
    customer_id: int | None
    customer_name: str | None = None
    conversation_id: str | None = None
    status: str
    requested_time: str | None
    fulfillment_type: str | None = None
    delivery_address: str | None = None
    payment_method: str | None = None
    total: float
    # --- Aviso de WhatsApp (ver app/integrations/wsp_notifications.py) ---
    whatsapp_status: str | None = None  # sent | failed | skipped_not_configured | skipped_no_phone
    whatsapp_sent_at: datetime | None = None
    items: list[OrderItemOut]


class OrderStatusUpdate(BaseModel):
    status: str


class AgentMessageIn(BaseModel):
    message: str
    conversation_id: str | None = None
    customer_phone: str | None = None
    customer_name: str | None = None
    channel: str = "web"


class ConversationTurnOut(BaseModel):
    role: str  # cliente | agente | sistema
    text: str


class ConversationOut(BaseModel):
    id: str
    channel: str
    status: str
    detail_status: str | None = None
    customer_name: str | None
    customer_phone: str | None
    outcome: str | None
    turns: int
    last_message: str | None
    created_at: datetime
    updated_at: datetime


class ConversationDetailOut(ConversationOut):
    transcript: list[ConversationTurnOut]
    order: OrderOut | None = None
    # Boleta/factura real emitida para el pedido de esta llamada (ver
    # app/domain/invoicing_services.py) -- None si el pedido no se llego a
    # confirmar, o si el negocio no tiene facturacion electronica activada.
    invoice: InvoiceOut | None = None


class ToolCallOut(BaseModel):
    name: str
    arguments: dict
    result: dict


class AgentTurnOut(BaseModel):
    response: str
    intent: str
    missing: list[str] = []
    tool_calls: list[ToolCallOut] = []
    order: OrderOut | None = None
    conversation_id: str
    status: str
