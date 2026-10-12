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

Token interno = "<conversation_id>.<vence_en_epoch>.<firma>", HMAC-SHA256
(mismo patron que el login del panel -- ver frontend/lib/auth.ts -- pero
del lado del backend, con el stdlib de Python). Lo que de verdad va en la
URL es ESE string entero codificado en base64url -- nunca el string
"crudo" con puntos y dos puntos sueltos.

Bug real, visto en vivo en la primera llamada que probo esto: el
conversation_id real (call_control_id de Telnyx) trae un ":" literal, ej.
"v3:sFijHoZ...". Un ":" es un caracter valido en un path de URL sin
escapar, pero WhatsApp (al generar la vista previa del link) y Next.js
(al leer el segmento dinamico [token]) no coincidian en si ese ":" debia
viajar codificado como "%3A" o no -- el resultado era que el valor
llegaba A LA PAGINA como el texto literal "%3A" (nunca decodificado), y
el fetch de la pagina hacia el backend lo volvia a codificar
(encodeURIComponent sobre un string que ya tenia un "%" -> "%253A"),
dando un 404 real al cliente que tocaba el link desde WhatsApp.
Base64url (alfabeto A-Za-z0-9_-, sin ":" ni "." ni "%") no tiene esa
ambiguedad en ningun punto de la cadena -- WhatsApp/navegador/Next.js/
FastAPI lo pasan tal cual, sin nada que codificar ni decodificar nunca.
No hay tabla nueva en la base de datos: el pedido en curso vive en
memoria (ConversationState, ver agents/state.py) hasta que se confirma
de verdad, asi que no hay nada que persistir para esto.
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


def _encode_for_url(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8").rstrip("=")


def _decode_from_url(token: str) -> str | None:
    # binascii.Error (base64 mal formado) es subclase de ValueError, igual
    # que UnicodeDecodeError (bytes que no son UTF-8 valido una vez
    # decodificados) -- un token cualquiera pegado a mano cae aca, nunca
    # debe tirar, solo "no es un token valido".
    try:
        padded = token + "=" * (-len(token) % 4)
        return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
    except ValueError:
        return None


def create_review_token(conversation_id: str) -> str:
    expires_at = int(time.time()) + TOKEN_TTL_SECONDS
    payload = f"{conversation_id}.{expires_at}"
    raw_token = f"{payload}.{_sign(payload)}"
    return _encode_for_url(raw_token)


def verify_review_token(token: str) -> str | None:
    """None si el token esta mal formado, firmado con otra clave, o
    vencido."""
    raw_token = _decode_from_url(token)
    if raw_token is None:
        return None
    # rsplit (no split): el conversation_id en si puede traer puntos --
    # los dos ultimos segmentos son siempre vencimiento y firma.
    parts = raw_token.rsplit(".", 2)
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
