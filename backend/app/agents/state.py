"""Memoria de llamada en curso. Vive en proceso (dict) porque el objetivo
de este sprint es validar el runtime completo; cuando haya Redis, este
modulo pasa a ser el unico que cambia (la interfaz de `get_or_create`/`reset`
se mantiene igual)."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OrderLineDraft:
    product_id: int
    name: str
    quantity: int
    unit_price: float
    notes: str | None = None


@dataclass
class ConversationState:
    id: str
    tenant_id: str
    status: str = "collecting"  # collecting | awaiting_confirmation | closed
    items: list[OrderLineDraft] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    customer: dict[str, Any] | None = None
    requested_time: str | None = None
    transcript: list[str] = field(default_factory=list)
    last_touched_at: float = field(default_factory=time.monotonic)


_STORE: dict[str, ConversationState] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def get_or_create(conversation_id: str | None, tenant_id: str) -> ConversationState:
    if conversation_id and conversation_id in _STORE:
        state = _STORE[conversation_id]
        state.last_touched_at = time.monotonic()
        return state
    new_id = conversation_id or str(uuid.uuid4())
    state = ConversationState(id=new_id, tenant_id=tenant_id)
    _STORE[new_id] = state
    return state


def sweep_stale(max_age_seconds: float = 3600) -> int:
    """Limpia conversaciones abandonadas (el usuario/llamante nunca cerro
    la conversacion ni disparo call.hangup/voice_status: red caida, colgo
    sin avisar, etc). No se invoca automaticamente en ningun lado todavia
    -- el siguiente paso natural es llamarla desde una tarea periodica
    (APScheduler, un cron, o un background task de FastAPI) una vez haya
    mas de un proceso vivo. Se deja lista y probada para ese momento."""
    now = time.monotonic()
    stale = [cid for cid, state in _STORE.items() if now - state.last_touched_at > max_age_seconds]
    for cid in stale:
        reset(cid)
    return len(stale)


def get_lock(conversation_id: str) -> asyncio.Lock:
    """Un lock por conversacion: si Twilio/Telnyx reintenta un webhook
    porque tardamos en responder (Gemini puede demorar varios segundos),
    esto evita procesar el mismo turno dos veces en paralelo y duplicar
    items/pedidos."""
    lock = _LOCKS.get(conversation_id)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[conversation_id] = lock
    return lock


def reset(conversation_id: str) -> None:
    _STORE.pop(conversation_id, None)
    _LOCKS.pop(conversation_id, None)
