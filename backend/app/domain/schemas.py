from datetime import datetime

from pydantic import BaseModel, Field


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    description: str | None
    price: float
    category: str
    stock_available: int


class CustomerCreate(BaseModel):
    name: str
    phone: str | None = None
    address: str | None = None
    notes: str | None = None


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
