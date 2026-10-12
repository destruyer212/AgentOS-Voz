"""Carrito visual durante la llamada (ver
docs/08-mejora-carrito-visual-en-llamada.md).

Modulo nuevo y AISLADO a proposito -- el pedido explicito fue "hazlo en
una parte aparte, asi si no sale bien la podemos eliminar". El unico
punto de enganche con el resto del sistema esta en agents/runtime.py
(dispara el WhatsApp con el link cuando el pedido llega a
"awaiting_confirmation" por telefono) y en wsp_notifications.py (una
funcion nueva, notify_order_review_link). Todo lo demas -- este archivo,
su router (api/v1/order_review.py), y la pagina del frontend -- se puede
borrar entero sin dejar nada roto.

Token = "<conversation_id>.<vence_en_epoch>.<firma>", firmado con HMAC-
SHA256 (mismo patron que el login del panel -- ver frontend/lib/auth.ts
-- pero del lado del backend, con el stdlib de Python). No hay tabla
nueva en la base de datos: el pedido en curso vive en memoria
(ConversationState, ver agents/state.py) hasta que se confirma de
verdad, asi que no hay nada que persistir para esto.
"""

import base64
import hashlib
import hmac
import time

from app.infrastructure.config import settings

# 30 minutos -- mismo plazo que recomienda el MVP del doc: la llamada real
# dura unos minutos, no horas.
TOKEN_TTL_SECONDS = 30 * 60


def _secret() -> bytes:
    return (settings.order_review_secret or "dev-secret-order-review-cambiar-en-produccion").encode("utf-8")


def _sign(payload: str) -> str:
    digest = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def create_review_token(conversation_id: str) -> str:
    expires_at = int(time.time()) + TOKEN_TTL_SECONDS
    payload = f"{conversation_id}.{expires_at}"
    return f"{payload}.{_sign(payload)}"


def verify_review_token(token: str) -> str | None:
    """None si el token esta mal formado, firmado con otra clave, o
    vencido. rsplit (no split) porque el conversation_id en si puede traer
    puntos -- los dos ultimos segmentos son siempre vencimiento y firma."""
    parts = token.rsplit(".", 2)
    if len(parts) != 3:
        return None
    conversation_id, expires_at_raw, signature = parts
    if not conversation_id:
        return None
    expected = _sign(f"{conversation_id}.{expires_at_raw}")
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        expires_at = int(expires_at_raw)
    except ValueError:
        return None
    if time.time() > expires_at:
        return None
    return conversation_id


def build_review_link(conversation_id: str) -> str:
    token = create_review_token(conversation_id)
    base = settings.frontend_public_url.rstrip("/")
    return f"{base}/revisar/{token}"
