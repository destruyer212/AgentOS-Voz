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
    document_url: str | None = None,
    document_label: str | None = None,
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
    # Link a la boleta/factura electronica real (PDF de SUNAT via
    # apisunat.pe) -- omitido si no se pudo emitir (ver
    # AgentRuntime._issue_invoice_and_notify), nunca en null, mismo motivo
    # que "address" arriba.
    if document_url:
        payload["documentUrl"] = document_url
        if document_label:
            payload["documentLabel"] = document_label
    return payload


async def notify_order_confirmed(
    order: OrderOut,
    customer_phone: str | None,
    document_url: str | None = None,
    document_label: str | None = None,
) -> str:
    """Llamar SIEMPRE via fire_and_forget(), nunca con await directo desde
    el flujo de una llamada o chat en curso. Devuelve el estado del envio
    ("sent"/"failed"/"skipped_not_configured"/"skipped_no_phone") para que
    quien la llama (ver AgentRuntime._issue_invoice_and_notify) pueda
    guardarlo en el pedido y mostrarlo de verdad en el panel de Llamadas,
    en vez de asumir que "se disparo" significa "llego"."""
    return await _send_notification(
        order, customer_phone, "order_confirmed", document_url=document_url, document_label=document_label
    )


async def notify_order_dispatched(order: OrderOut, customer_phone: str | None) -> str:
    """Aviso de "ya salio con el motorizado" -- se dispara cuando el
    encargado marca el pedido como "dispatched" desde el panel de Pedidos
    (ver app/api/v1/orders.py). Llamar SIEMPRE via fire_and_forget(), nunca
    con await directo desde el handler HTTP: un wsp-service caido o lento
    jamas debe demorar la respuesta al encargado que esta despachando."""
    return await _send_notification(
        order, customer_phone, "order_on_the_way", estimated_time=settings.delivery_eta_label
    )


async def notify_order_ready_for_pickup(order: OrderOut, customer_phone: str | None) -> str:
    """Aviso de "ya esta listo para recoger" -- se dispara cuando un pedido
    de recojo en el local (nunca delivery, ese usa notify_order_dispatched)
    pasa a "ready". Mismo contrato que notify_order_dispatched: siempre
    fire_and_forget()."""
    return await _send_notification(order, customer_phone, "order_ready_for_pickup")


async def _send_notification(
    order: OrderOut,
    customer_phone: str | None,
    notification_type: str,
    estimated_time: str | None = None,
    document_url: str | None = None,
    document_label: str | None = None,
) -> str:
    if not settings.wsp_service_url or not settings.wsp_service_api_key:
        return "skipped_not_configured"  # feature apagada: no configurado

    payload = build_order_notification_payload(
        order, customer_phone, notification_type, estimated_time, document_url, document_label
    )
    if payload is None:
        logger.info(
            "wsp-service: sin telefono de cliente, no se manda aviso order_id=%s type=%s",
            order.id, notification_type,
        )
        return "skipped_no_phone"

    url = f"{settings.wsp_service_url.rstrip('/')}/api/notifications/order"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload, headers={"x-api-key": settings.wsp_service_api_key})
        if resp.status_code in (200, 202):
            logger.info(
                "wsp-service: aviso encolado order_id=%s type=%s status_code=%s",
                order.id, notification_type, resp.status_code,
            )
            return "sent"
        logger.warning(
            "wsp-service: respuesta inesperada order_id=%s type=%s status_code=%s body=%s",
            order.id, notification_type, resp.status_code, resp.text[:300],
        )
        return "failed"
    except Exception:
        # A proposito sin re-lanzar: esto corre desatado del turno real, no
        # hay nadie mas escuchando este error salvo el log.
        logger.exception(
            "wsp-service: fallo al mandar aviso de WhatsApp order_id=%s type=%s", order.id, notification_type
        )
        return "failed"


async def notify_order_review_link(
    conversation_id: str,
    customer_name: str | None,
    customer_phone: str | None,
    review_link: str,
    items: list[dict],
    total: float,
    fulfillment_type: str | None,
    delivery_address: str | None,
    payment_method: str | None,
) -> str:
    """Carrito visual durante la llamada (ver
    docs/08-mejora-carrito-visual-en-llamada.md,
    app/domain/order_review.py) -- manda el link de revision apenas el
    pedido llega al resumen final por telefono. Separada de
    _send_notification/build_order_notification_payload a proposito:
    todavia NO existe un Order real en este punto (recien se crea cuando
    el cliente confirma), asi que no hay un OrderOut que pasarle a esas
    funciones -- los datos vienen directo del ConversationState en
    memoria (ver agents/runtime.py).

    Reutiliza el tipo 'order_received' del lado de wsp-service (el mas
    parecido semanticamente -- "ya lo estamos revisando", ver
    schemas.js/templates.js en whatsapp-service): es un tipo "detallado"
    ahi, asi que items/total son obligatorios igual que en un aviso real.
    El link va en 'notes', el unico campo de texto libre que el template
    deja pasar tal cual -- evita tener que tocar el repo separado de
    wsp-service para esto. Llamar SIEMPRE via fire_and_forget()."""
    if not settings.wsp_service_url or not settings.wsp_service_api_key:
        return "skipped_not_configured"
    if not customer_phone:
        logger.info(
            "wsp-service: sin telefono de cliente, no se manda link de revision conversation_id=%s",
            conversation_id,
        )
        return "skipped_no_phone"

    payload: dict = {
        "orderId": conversation_id[:64],
        "type": "order_received",
        "customerName": customer_name or "Cliente",
        "customerPhone": customer_phone,
        "deliveryType": fulfillment_type or "pickup",
        "items": [
            {"name": item["name"][:120], "quantity": item["quantity"], "price": item["unit_price"]}
            for item in items
        ],
        "total": total,
        "notes": f"Revisa tu pedido aquí antes de confirmar: {review_link}",
    }
    if fulfillment_type == "delivery" and delivery_address:
        payload["address"] = delivery_address
    if payment_method:
        payload["paymentMethod"] = payment_method

    url = f"{settings.wsp_service_url.rstrip('/')}/api/notifications/order"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload, headers={"x-api-key": settings.wsp_service_api_key})
        if resp.status_code in (200, 202):
            logger.info(
                "wsp-service: link de revision encolado conversation_id=%s status_code=%s",
                conversation_id, resp.status_code,
            )
            return "sent"
        logger.warning(
            "wsp-service: respuesta inesperada mandando link de revision conversation_id=%s status_code=%s body=%s",
            conversation_id, resp.status_code, resp.text[:300],
        )
        return "failed"
    except Exception:
        logger.exception(
            "wsp-service: fallo al mandar link de revision conversation_id=%s", conversation_id
        )
        return "failed"
