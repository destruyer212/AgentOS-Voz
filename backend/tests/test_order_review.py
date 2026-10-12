"""Carrito visual durante la llamada (ver
docs/08-mejora-carrito-visual-en-llamada.md,
app/domain/order_review.py, app/api/v1/order_review.py). Cubre lo que de
verdad puede salir mal: un token firmado con otra clave o ya vencido
dejando ver el pedido de otra persona, y que el snapshot nunca muestre un
total distinto al que el agente ya dijo por voz."""

import time

import pytest
from fastapi import HTTPException

from app.agents.state import OrderLineDraft, get_or_create, reset
from app.api.v1.order_review import get_order_review
from app.domain.order_review import (
    TOKEN_TTL_SECONDS,
    build_review_link,
    create_review_token,
    verify_review_token,
)
from app.infrastructure.config import settings


@pytest.fixture(autouse=True)
def _review_secret(monkeypatch):
    monkeypatch.setattr(settings, "order_review_secret", "test-secret-order-review")
    yield


def test_verify_round_trips_a_freshly_created_token():
    token = create_review_token("conv-123")
    assert verify_review_token(token) == "conv-123"


def test_verify_rejects_a_tampered_signature():
    token = create_review_token("conv-123")
    tampered = token[:-2] + "xx"
    assert verify_review_token(tampered) is None


def test_verify_rejects_garbage():
    assert verify_review_token("no-es-un-token-valido") is None


def test_verify_rejects_expired_token(monkeypatch):
    # Fuerza el "ahora" al momento de crear el token, y vuelve a correr el
    # tiempo real bien pasado el vencimiento -- sin depender de esperar
    # TOKEN_TTL_SECONDS de verdad.
    token = create_review_token("conv-vencido")
    future = time.time() + TOKEN_TTL_SECONDS + 1
    monkeypatch.setattr(time, "time", lambda: future)
    assert verify_review_token(token) is None


def test_verify_rejects_token_signed_with_a_different_secret(monkeypatch):
    token = create_review_token("conv-123")
    monkeypatch.setattr(settings, "order_review_secret", "otro-secreto-distinto")
    assert verify_review_token(token) is None


def test_conversation_id_with_dots_round_trips():
    # rsplit, no split: el conversation_id en si puede traer puntos (no es
    # el caso hoy, pero el formato del token no debe asumir que nunca los
    # trae) -- solo los ultimos dos segmentos son vencimiento y firma.
    token = create_review_token("v3:algo.con.puntos")
    assert verify_review_token(token) == "v3:algo.con.puntos"


def test_token_is_url_safe_for_a_real_telnyx_call_control_id():
    # Bug real, visto en vivo en la primera llamada que probo esto: un
    # conversation_id con ":" (call_control_id real de Telnyx, ej.
    # "v3:sFijHoZ...") viajando SIN codificar en el path de la URL
    # terminaba con un "%3A" literal segun quien lo tocara (WhatsApp,
    # Next.js, el fetch al backend) -- el cliente que tocaba el link desde
    # WhatsApp recibia un 404. El token que va en la URL tiene que ser
    # base64url puro (A-Za-z0-9_-, sin ":" ni "." ni "%") para que nadie
    # en la cadena tenga nada que codificar/decodificar.
    conversation_id = "v3:sFijHoZeYNyHvQl1goikrud1LmjuJy79gw3pTLeuHhxcVk3iwB57og"
    token = create_review_token(conversation_id)
    assert all(c.isalnum() or c in "-_" for c in token)
    assert verify_review_token(token) == conversation_id


def test_build_review_link_uses_configured_frontend_url(monkeypatch):
    monkeypatch.setattr(settings, "frontend_public_url", "https://ejemplo.vercel.app/")
    link = build_review_link("conv-123")
    assert link.startswith("https://ejemplo.vercel.app/revisar/")
    token = link.rsplit("/revisar/", 1)[1]
    assert verify_review_token(token) == "conv-123"


@pytest.mark.asyncio
async def test_get_order_review_404s_on_invalid_token():
    with pytest.raises(HTTPException) as exc_info:
        await get_order_review("token-invalido")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_order_review_404s_when_conversation_no_longer_exists():
    token = create_review_token("conv-que-nunca-existio")
    with pytest.raises(HTTPException) as exc_info:
        await get_order_review(token)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_order_review_returns_live_snapshot_matching_voice_total():
    conversation_id = "conv-review-snapshot"
    try:
        state = get_or_create(conversation_id, settings.default_tenant_id)
        state.channel = "phone"
        state.status = "awaiting_confirmation"
        state.items = [
            OrderLineDraft(product_id=1, name="Hamburguesa Clasica", quantity=2, unit_price=15.0),
        ]
        state.fulfillment_type = "delivery"
        state.delivery_address = "Av. Test 123"
        state.payment_method = "yape"
        state.customer = {"name": "Carlos"}

        token = create_review_token(conversation_id)
        review = await get_order_review(token)

        assert review.status == "awaiting_confirmation"
        assert review.awaiting_confirmation is True
        assert review.customer_name == "Carlos"
        assert [item.name for item in review.items] == ["Hamburguesa Clasica"]
        assert review.subtotal == 30.0
        assert review.delivery_fee == settings.delivery_fee_soles
        assert review.total == round(30.0 + settings.delivery_fee_soles, 2)
        assert review.fulfillment_type == "delivery"
        assert review.delivery_address == "Av. Test 123"
        assert review.payment_method == "yape"
    finally:
        reset(conversation_id)


@pytest.mark.asyncio
async def test_get_order_review_pickup_has_no_delivery_fee():
    conversation_id = "conv-review-pickup"
    try:
        state = get_or_create(conversation_id, settings.default_tenant_id)
        state.items = [OrderLineDraft(product_id=1, name="Chaufa", quantity=1, unit_price=20.0)]
        state.fulfillment_type = "pickup"

        token = create_review_token(conversation_id)
        review = await get_order_review(token)

        assert review.delivery_fee == 0.0
        assert review.total == 20.0
    finally:
        reset(conversation_id)
