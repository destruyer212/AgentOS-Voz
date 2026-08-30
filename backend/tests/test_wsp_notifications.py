"""Aviso de pedido confirmado por WhatsApp (wsp-service, microservicio
separado). Cubre solo la logica pura -- construccion del payload y el
apagado en silencio cuando no esta configurado -- nunca pega a la red real
en tests (ver tests/conftest.py, que fuerza WSP_SERVICE_URL/API_KEY vacias
antes de importar `app`)."""

import pytest

from app.domain.schemas import OrderItemOut, OrderOut
from app.integrations import wsp_notifications as wsp


def _order(**overrides) -> OrderOut:
    base = {
        "id": 42,
        "customer_id": 1,
        "customer_name": "Carlos",
        "conversation_id": "convo-1",
        "status": "confirmed",
        "requested_time": None,
        "fulfillment_type": "pickup",
        "delivery_address": None,
        "payment_method": "yape",
        "total": 44.0,
        "items": [
            OrderItemOut(
                product_id=32, product_name="Pollo a la Brasa para Dos", quantity=1, unit_price=44.0, notes=None
            )
        ],
    }
    base.update(overrides)
    return OrderOut(**base)


def test_build_payload_returns_none_without_phone():
    assert wsp.build_order_notification_payload(_order(), None) is None
    assert wsp.build_order_notification_payload(_order(), "") is None


def test_build_payload_pickup_omits_address():
    payload = wsp.build_order_notification_payload(_order(), "+51923648424")
    assert payload["orderId"] == "42"
    assert payload["type"] == "order_confirmed"
    assert payload["customerPhone"] == "+51923648424"
    assert payload["deliveryType"] == "pickup"
    assert "address" not in payload  # omitida, no null -- ver nota en wsp_notifications.py
    assert payload["items"] == [{"name": "Pollo a la Brasa para Dos", "quantity": 1, "price": 44.0}]


def test_build_payload_delivery_includes_address():
    order = _order(fulfillment_type="delivery", delivery_address="Av. Test 123")
    payload = wsp.build_order_notification_payload(order, "+51923648424")
    assert payload["deliveryType"] == "delivery"
    assert payload["address"] == "Av. Test 123"


@pytest.mark.asyncio
async def test_notify_order_confirmed_noop_when_not_configured():
    """Sin WSP_SERVICE_URL/API_KEY (el caso en tests, ver conftest.py) no
    debe intentar red ni tirar excepcion -- simplemente no hace nada."""
    await wsp.notify_order_confirmed(_order(), "+51923648424")
