"""Memoria de llamada en curso. Vive en proceso (dict) porque el objetivo
de este sprint es validar el runtime completo; cuando haya Redis, este
modulo pasa a ser el unico que cambia (la interfaz de `get_or_create`/`reset`
se mantiene igual)."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
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
    channel: str = "web"
    # collecting | need_name | need_fulfillment | need_address | need_payment |
    # need_document | need_dni | need_ruc | awaiting_confirmation | closed
    status: str = "collecting"
    items: list[OrderLineDraft] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    customer: dict[str, Any] | None = None
    requested_time: str | None = None
    transcript: list[str] = field(default_factory=list)
    last_touched_at: float = field(default_factory=time.monotonic)
    silence_retries: int = 0
    speaking: bool = False  # True mientras el agente esta reproduciendo audio (telefonia, barge-in)
    # Datos de entrega/pago que el agente pregunta antes de cerrar el pedido
    # (ver AgentRuntime._next_missing_detail). has_real_name distingue un
    # nombre real (dado por el cliente o ya en la ficha) del fallback
    # "Cliente telefonico" que se usa solo para poder crear el registro.
    has_real_name: bool = False
    fulfillment_type: str | None = None  # delivery | pickup
    delivery_address: str | None = None
    payment_method: str | None = None  # efectivo | yape | plin | tarjeta
    # Observabilidad (ver VoiceTurnMetric en domain/models.py): timestamp de
    # inicio del turno en curso, para medir cuanto tarda AgentRuntime en
    # responder -- el tramo que si controlamos (Deepgram/Telnyx no exponen
    # su propia latencia interna de STT/TTS). No se persiste a DB, solo vive
    # mientras dura el turno.
    turn_started_at: float | None = None
    used_fallback_this_turn: bool = False
    # Ultima pregunta de desambiguacion de producto pendiente (ej. "Cual
    # hamburguesa prefieres: BBQ, Clasica, Doble, Vegetariana?"), para poder
    # resolver una respuesta elptica como "vegetariana" o "Pero te dije
    # vegetariana" en el turno siguiente -- ver
    # AgentRuntime._resolve_pending_clarification. None si no hay ninguna
    # pregunta de este tipo pendiente.
    pending_clarification: dict[str, Any] | None = None
    # Señal para telefonia (ver voice_agent_bridge.py): el pedido se
    # confirmo de verdad en este turno, asi que en cuanto termine de sonar
    # la respuesta de despedida, hay que colgar la llamada sola. Separado
    # de status=="closed" a proposito -- ese mismo status tambien se usa
    # para handoff, y ahi colgar seria mucho peor que no colgar.
    hangup_after_response: bool = False
    # Direccion de delivery rechazada por estar fuera de zona (ver
    # domain/delivery_zones.py) -- guarda el mensaje explicandolo para que
    # AgentRuntime._advance_order lo repita en vez del generico "¿cual es la
    # direccion?" cuando vuelve a preguntar. None si la ultima direccion
    # dada (si hubo alguna) fue aceptada o si todavia no se pidio ninguna.
    pending_zone_rejection_message: str | None = None
    # Direccion ya dada por el cliente pero sin ningun distrito reconocible
    # (ver domain/delivery_zones.address_names_known_district) -- se guarda
    # aca mientras se pregunta explicitamente "¿a que distrito pertenece?"
    # para poder juntarla con esa respuesta en el siguiente turno en vez de
    # tratarla como una direccion nueva que reemplaza a la anterior. None
    # si no hay ninguna direccion esperando distrito.
    pending_address_awaiting_district: str | None = None
    # Facturacion electronica (ver domain/invoicing_services.py). En voz se
    # pregunta explicitamente si quiere boleta o factura antes de confirmar:
    # boleta exige DNI de 8 digitos, factura exige RUC de 11. En web/WhatsApp
    # se conserva el comportamiento historico: boleta automatica salvo que el
    # cliente pida factura.
    invoice_document_type: str | None = None  # boleta | factura
    boleta_dni: str | None = None
    wants_factura: bool = False
    factura_ruc: str | None = None
    factura_razon_social: str | None = None
    # Mensajes listos para repetir si el comprobante/documento no se pudo
    # reconocer -- mismo patron que pending_zone_rejection_message.
    pending_document_rejection_message: str | None = None
    pending_dni_rejection_message: str | None = None
    pending_ruc_rejection_message: str | None = None


_STORE: dict[str, ConversationState] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def peek(conversation_id: str) -> ConversationState | None:
    """Como get_or_create, pero NUNCA crea una entrada nueva -- solo mira si
    ya existe. Pensado para quien necesita saber "ya habia una conversacion
    para este ID" sin la logica de negocio completa del runtime (ver
    voice_agent_bridge.py: decidir si repetir el saludo completo o no
    cuando Telnyx reconecta el stream de audio a mitad de una llamada)."""
    return _STORE.get(conversation_id)


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


# Llamadas ya colgadas, compartido entre el flujo viejo de Call Control
# (telephony_telnyx.py) y el puente nuevo de Voice Agent (agent_llm_proxy.py):
# ambos pueden recibir un evento/request tardio para el MISMO call_control_id
# despues de que call.hangup ya se proceso y reset() ya vacio el estado. Sin
# este marcador compartido, un "think" tardio de Deepgram que llega justo
# despues del hangup (la llamada ya termino, pero Deepgram todavia estaba
# terminando de pensar la ultima frase) pasaba por get_or_create(), creaba un
# ConversationState nuevo en blanco, y _persist_conversation() volvia a poner
# "active" una conversacion que el hangup ya habia cerrado -- una llamada
# fantasma reabierta en la DB despues de haber terminado. Vive separado de
# _STORE/_LOCKS a proposito: reset() los vacia, pero esto tiene que sobrevivir
# para poder reconocer que ese call_control_id ya no existe.
_MAX_HUNG_UP = 500
_hung_up_calls: set[str] = set()
_hung_up_order: deque[str] = deque(maxlen=_MAX_HUNG_UP)


def mark_hung_up(conversation_id: str) -> None:
    if conversation_id in _hung_up_calls:
        return
    if len(_hung_up_order) >= _MAX_HUNG_UP:
        oldest = _hung_up_order.popleft()
        _hung_up_calls.discard(oldest)
    _hung_up_order.append(conversation_id)
    _hung_up_calls.add(conversation_id)


def is_hung_up(conversation_id: str) -> bool:
    return conversation_id in _hung_up_calls
