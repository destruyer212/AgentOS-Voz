"""Aviso de pedido confirmado por WhatsApp, via wsp-service -- microservicio
Baileys separado (repo y despliegue propios, cuenta AWS distinta a esta;
ver C:\\whatsapp-service\\DEPLOYMENT.md en esa maquina).

Contrato minimo para no romper nunca la llamada real:
- Opcional: si WSP_SERVICE_URL / WSP_SERVICE_API_KEY no estan configuradas,
  se salta en silencio (feature apagada).
- Nunca se hace `await` de esto en el flujo de la llamada -- se dispara con
  fire_and_forget() y sigue en paralelo. Un WhatsApp caido, lento o mal
  configurado jamas debe agregar latencia ni hacer fallar la confirmacion
  del pedido.
- No toca la sesion de base de datos del turno (podria estar cerrada para
  cuando esta corutina corra) -- solo HTTP + logging.
"""

import asyncio
import logging

import httpx

from app.domain.schemas import OrderOut
from app.infrastructure.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5.0

# asyncio solo mantiene una referencia debil a las tasks creadas con
# create_task -- sin guardarlas en algun lado, el garbage collector puede
# tirarlas a mitad de ejecucion. Se van soltando solas al terminar.
_background_tasks: set[asyncio.Task] = set()


def fire_and_forget(coro) -> None:
    """Programa `coro` para correr en paralelo, sin esperarla y sin dejar
    que una excepcion adentro se propague al llamador."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def build_order_notification_payload(
    order: OrderOut,
    customer_phone: str | None,
    notification_type: str = "order_confirmed",
    estimated_time: str | None = None,
) -> dict | None:
    """None si falta lo minimo para mandar el aviso (sin telefono no hay a
    donde escribirle)."""
    if not customer_phone:
        return None
    is_delivery = order.fulfillment_type == "delivery"
    payload: dict = {
        "orderId": str(order.id),
        "type": notification_type,
        "restaurantName": settings.restaurant_name,
        "customerName": order.customer_name or "Cliente",
        "customerPhone": customer_phone,
        "total": order.total,
        "currency": "PEN",
        "deliveryType": "delivery" if is_delivery else "pickup",
        "items": [
            {"name": item.product_name, "quantity": item.quantity, "price": item.unit_price}
            for item in order.items
        ],
    }
    # Bug real, visto al probar contra wsp-service de verdad: su schema
    # (Zod) usa `.optional()` en `address`, que acepta la clave ausente
    # pero NO `null` -- mandar "address": null tiraba 400 "Expected
    # string, received null". Por eso se omite la clave entera en vez de
    # mandarla en null cuando es recojo en el local.
    if is_delivery and order.delivery_address:
        payload["address"] = order.delivery_address
    # Mismo motivo que "address": la clave se omite entera si no hay tiempo
    # estimado, nunca se manda en null (ver wsp-service/api/schemas.js,
    # `estimatedTime` tambien es `.optional()`).
    if estimated_time:
        payload["estimatedTime"] = estimated_time
    return payload


async def notify_order_confirmed(order: OrderOut, customer_phone: str | None) -> None:
    """Llamar SIEMPRE via fire_and_forget(), nunca con await directo desde
    el flujo de una llamada o chat en curso."""
    await _send_notification(order, customer_phone, "order_confirmed")


async def notify_order_dispatched(order: OrderOut, customer_phone: str | None) -> None:
    """Aviso de "ya salio con el motorizado" -- se dispara cuando el
    encargado marca el pedido como "dispatched" desde el panel de Pedidos
    (ver app/api/v1/orders.py). Llamar SIEMPRE via fire_and_forget(), nunca
    con await directo desde el handler HTTP: un wsp-service caido o lento
    jamas debe demorar la respuesta al encargado que esta despachando."""
    await _send_notification(
        order, customer_phone, "order_on_the_way", estimated_time=settings.delivery_eta_label
    )


async def notify_order_ready_for_pickup(order: OrderOut, customer_phone: str | None) -> None:
    """Aviso de "ya esta listo para recoger" -- se dispara cuando un pedido
    de recojo en el local (nunca delivery, ese usa notify_order_dispatched)
    pasa a "ready". Mismo contrato que notify_order_dispatched: siempre
    fire_and_forget()."""
    await _send_notification(order, customer_phone, "order_ready_for_pickup")


async def _send_notification(
    order: OrderOut,
    customer_phone: str | None,
    notification_type: str,
    estimated_time: str | None = None,
) -> None:
    if not settings.wsp_service_url or not settings.wsp_service_api_key:
        return  # feature apagada: no configurado

    payload = build_order_notification_payload(order, customer_phone, notification_type, estimated_time)
    if payload is None:
        logger.info(
            "wsp-service: sin telefono de cliente, no se manda aviso order_id=%s type=%s",
            order.id, notification_type,
        )
        return

    url = f"{settings.wsp_service_url.rstrip('/')}/api/notifications/order"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload, headers={"x-api-key": settings.wsp_service_api_key})
        if resp.status_code in (200, 202):
            logger.info(
                "wsp-service: aviso encolado order_id=%s type=%s status_code=%s",
                order.id, notification_type, resp.status_code,
            )
        else:
            logger.warning(
                "wsp-service: respuesta inesperada order_id=%s type=%s status_code=%s body=%s",
                order.id, notification_type, resp.status_code, resp.text[:300],
            )
    except Exception:
        # A proposito sin re-lanzar: esto corre desatado del turno real, no
        # hay nadie mas escuchando este error salvo el log.
        logger.exception(
            "wsp-service: fallo al mandar aviso de WhatsApp order_id=%s type=%s", order.id, notification_type
        )
