from pydantic import BaseModel, Field


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    description: str | None
    price: float
    stock_available: int


class CustomerCreate(BaseModel):
    name: str
    phone: str | None = None
    address: str | None = None
    notes: str | None = None


class CustomerOut(CustomerCreate):
    id: int


class OrderItemIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    notes: str | None = None


class OrderCreate(BaseModel):
    customer_id: int | None = None
    requested_time: str | None = None
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
    status: str
    requested_time: str | None
    total: float
    items: list[OrderItemOut]


class AgentMessageIn(BaseModel):
    message: str
    conversation_id: str | None = None
    customer_phone: str | None = None
    customer_name: str | None = None


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
