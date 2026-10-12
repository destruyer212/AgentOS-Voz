"""Carrito visual durante la llamada -- ver
docs/08-mejora-carrito-visual-en-llamada.md y app/domain/order_review.py.

Publico a proposito (sin login, sin header de tenant): el token firmado
YA es la autorizacion -- solo quien recibio el link por WhatsApp puede
ver este pedido en particular. Solo lectura, a proposito tambien: el
pedido sigue viviendo en la llamada de voz (fuente de verdad real), esta
pagina es un espejo para que el cliente lo revise, no un control remoto
de la llamada -- evita el problema real de que confirmar/cancelar desde
la web deje la llamada telefonica colgando a mitad de una despedida que
nunca se escucho.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.state import ConversationState, peek
from app.domain.order_review import verify_review_token
from app.infrastructure.config import settings

router = APIRouter(prefix="/order-review", tags=["order-review"])


class OrderReviewItemOut(BaseModel):
    name: str
    quantity: int
    unit_price: float
    notes: str | None = None


class OrderReviewOut(BaseModel):
    status: str
    channel: str
    customer_name: str | None
    items: list[OrderReviewItemOut]
    subtotal: float
    delivery_fee: float
    total: float
    fulfillment_type: str | None
    delivery_address: str | None
    payment_method: str | None
    invoice_document_type: str | None
    boleta_dni: str | None
    boleta_dni_name: str | None
    factura_ruc: str | None
    factura_razon_social: str | None
    awaiting_confirmation: bool
    closed: bool


def _snapshot(state: ConversationState) -> OrderReviewOut:
    subtotal = sum(item.quantity * item.unit_price for item in state.items)
    # Mismo cargo y misma condicion que _build_summary en agents/runtime.py
    # -- lo que se muestra aca tiene que calzar exacto con lo que el agente
    # dice por voz, nunca un total distinto.
    delivery_fee = settings.delivery_fee_soles if state.fulfillment_type == "delivery" else 0.0
    customer_name = state.customer.get("name") if state.customer else None
    return OrderReviewOut(
        status=state.status,
        channel=state.channel,
        customer_name=customer_name,
        items=[
            OrderReviewItemOut(name=item.name, quantity=item.quantity, unit_price=item.unit_price, notes=item.notes)
            for item in state.items
        ],
        subtotal=round(subtotal, 2),
        delivery_fee=delivery_fee,
        total=round(subtotal + delivery_fee, 2),
        fulfillment_type=state.fulfillment_type,
        delivery_address=state.delivery_address,
        payment_method=state.payment_method,
        invoice_document_type=state.invoice_document_type,
        boleta_dni=state.boleta_dni,
        boleta_dni_name=state.boleta_dni_name,
        factura_ruc=state.factura_ruc,
        factura_razon_social=state.factura_razon_social,
        awaiting_confirmation=state.status == "awaiting_confirmation",
        closed=state.status == "closed",
    )


@router.get("/{token}", response_model=OrderReviewOut)
async def get_order_review(token: str) -> OrderReviewOut:
    conversation_id = verify_review_token(token)
    if not conversation_id:
        raise HTTPException(status_code=404, detail="Este link ya no es válido o expiró.")
    state = peek(conversation_id)
    if not state:
        raise HTTPException(
            status_code=404,
            detail="Ese pedido ya no está disponible (puede que la llamada haya terminado).",
        )
    return _snapshot(state)
