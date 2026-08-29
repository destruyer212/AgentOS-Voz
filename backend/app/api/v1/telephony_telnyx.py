"""Webhook unico de Telnyx Call Control v2 (Sprint 7, alternativa a Twilio).

Igual que la integracion de Twilio, esto es solo transporte: el cerebro
sigue siendo `AgentRuntime`, el mismo que atiende el chat web. La
diferencia es el modelo de control: Twilio responde TwiML en el propio
request; Telnyx manda eventos async y nosotros reaccionamos con comandos
REST (`app/integrations/telnyx_client.py`).

Flujo (`call_control_id` de Telnyx = `conversation_id` del runtime):

  call.initiated (incoming)  -> answer()
  call.answered              -> primer turno del AgentRuntime -> speak(saludo) + start_transcription()
                                 (en paralelo, no en secuencia: ver barge-in abajo)
  call.speak.ended           -> si el turno anterior cerro: hangup()
                                 si no: solo rearma el watchdog de silencio (la escucha ya viene corriendo)
  call.transcription         -> parcial: nada mas que cancelar el watchdog (hay alguien hablando)
                                 final: turno del AgentRuntime -> speak(respuesta, interrupt=seguia_hablando)
  call.hangup                -> limpieza + auditoria (y cancela cualquier watchdog vivo)

BARGE-IN: la transcripcion arranca una sola vez (en call.answered) y NUNCA
se detiene entre turnos -- el sistema esta escuchando todo el tiempo, incluso
mientras el propio agente esta hablando. Si el que llama termina de hablar
mientras el agente seguia con la respuesta anterior, el siguiente `speak`
se manda con `stop: "current"`: corta el audio viejo y arranca el nuevo de
una. Limitacion real y asumida: el corte pasa cuando el turno nuevo ya esta
listo para hablarse (tras el paso por Gemini, ~1-1.3s), no en el instante
exacto en que el que llama empieza a hablar -- eso requeriria Voice Activity
Detection sobre audio crudo (Telnyx Media Streaming), que es una superficie
de API sin validar todavia. Esta version reusa Call Control, ya probado en
llamadas reales, a cambio de no ser "corte instantaneo a mitad de palabra".

Watchdog de silencio: si nadie dice nada en SILENCE_TIMEOUT_SECONDS despues
de que el agente termina de hablar, un timer por llamada dispara un
reintento hablado, y cuelga con disculpa tras demasiados reintentos en vez
de dejar al que llama esperando indefinidamente.

ADVERTENCIA HONESTA: el shape exacto del payload de `call.transcription`
(donde viene el texto y el flag de "segmento completo") no esta
documentado publicamente con certeza al momento de escribir esto. `_extract_transcript`
prueba varias rutas conocidas y loguea el payload completo si no encuentra
texto, para poder ajustarlo rapido si hace falta.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import AgentRuntime
from app.agents.state import get_lock
from app.agents.state import get_or_create as get_conversation_state
from app.agents.state import is_hung_up as _is_hung_up
from app.agents.state import mark_hung_up as _mark_hung_up
from app.agents.state import reset as reset_conversation
from app.api.deps import get_db, get_tenant_id
from app.domain.models import AuditLog, Conversation
from app.domain.schemas import AgentMessageIn
from app.infrastructure.config import settings
from app.integrations import telnyx_client as telnyx
from app.integrations.voice_agent_bridge import (
    is_voice_agent_bridge_ready,
    missing_voice_agent_bridge_settings,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telephony/telnyx", tags=["telephony-telnyx"])

ERROR_MESSAGE = "Tuvimos un problema técnico. Intenta llamar en un momento."
SILENCE_RETRY_MESSAGE = "No te escuché, ¿qué decías?"
SILENCE_GIVEUP_MESSAGE = "Sigo sin escucharte. Intenta llamar más tarde, ¡gracias!"
SILENCE_TIMEOUT_SECONDS = 8.0
MAX_SILENCE_RETRIES = 2

_silence_watchdogs: dict[str, asyncio.Task] = {}

# Deduplicacion de webhooks: Telnyx entrega "al menos una vez", no "exactamente
# una vez" -- si nuestra respuesta tarda o hay cualquier jitter de red, puede
# reenviar el MISMO evento. Visto en vivo: un call.speak.ended duplicado hizo
# que intentaramos start_transcription() dos veces sobre la misma llamada,
# la segunda choco con "ya hay una transcripcion en curso", eso disparo una
# excepcion no capturada, y el manejador de errores colgo la llamada real.
_MAX_SEEN_EVENTS = 2000
_seen_event_ids: set[str] = set()
_seen_event_order: deque[str] = deque(maxlen=_MAX_SEEN_EVENTS)


def _already_processed(event_id: str | None) -> bool:
    if not event_id:
        return False  # sin id no hay como deduplicar; dejamos pasar
    if event_id in _seen_event_ids:
        return True
    if len(_seen_event_order) >= _MAX_SEEN_EVENTS:
        oldest = _seen_event_order.popleft()
        _seen_event_ids.discard(oldest)
    _seen_event_order.append(event_id)
    _seen_event_ids.add(event_id)
    return False


# Llamadas ya colgadas: Deepgram/Telnyx pueden seguir mandando eventos de
# transcripcion "rezagados" (buffer de audio que se termina de vaciar) unos
# segundos DESPUES de que call.hangup ya se proceso. Sin este marcador, esos
# eventos tardios pasaban por get_or_create() -- que no encuentra el estado
# (ya se limpio con reset_conversation) y crea uno NUEVO en blanco -- y el
# runtime terminaba llamando a Gemini y despues a telnyx.speak() sobre una
# llamada que ya no existe (422 en loop, visto en vivo). Con esto se ignoran
# de una, sin gastar el turno. Registro compartido con agent_llm_proxy.py
# (ver app/agents/state.py): el mismo problema aplica al puente nuevo de
# Voice Agent, que recibe requests "think" tardios de Deepgram por el mismo
# call_control_id, no solo eventos de Call Control.


def _cancel_watchdog(call_control_id: str) -> None:
    task = _silence_watchdogs.pop(call_control_id, None)
    if task and not task.done():
        task.cancel()


def _arm_watchdog(call_control_id: str, tenant_id: str) -> None:
    """Un timer independiente del ciclo request/response normal: si no
    llega ninguna transcripcion en SILENCE_TIMEOUT_SECONDS, actua solo.
    Necesita su propia sesion de DB porque corre fuera del request que lo
    disparo (esa sesion ya se habra cerrado para cuando el timer despierte)."""
    _cancel_watchdog(call_control_id)
    _silence_watchdogs[call_control_id] = asyncio.create_task(
        _silence_watchdog(call_control_id, tenant_id)
    )


async def _silence_watchdog(call_control_id: str, tenant_id: str) -> None:
    try:
        await asyncio.sleep(SILENCE_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        return  # la transcripcion llego a tiempo, nada que hacer

    async with get_lock(call_control_id):
        state = get_conversation_state(call_control_id, tenant_id)
        state.silence_retries += 1
        logger.warning(
            "Silencio (intento %s) call_control_id=%s",
            state.silence_retries, call_control_id,
        )
        # No hace falta parar/reiniciar la transcripcion: nunca se detiene
        # entre turnos (barge-in), asi que sigue escuchando de todos modos.
        try:
            if state.silence_retries > MAX_SILENCE_RETRIES:
                await telnyx.speak(call_control_id, SILENCE_GIVEUP_MESSAGE, interrupt=state.speaking)
                await telnyx.hangup(call_control_id)
                reset_conversation(call_control_id)
            else:
                # call.speak.ended de este mensaje rearma el watchdog solo.
                await telnyx.speak(call_control_id, SILENCE_RETRY_MESSAGE, interrupt=state.speaking)
                state.speaking = True
        except Exception:
            logger.exception("Fallo el watchdog de silencio para call_control_id=%s", call_control_id)


def _extract_transcript(payload: dict[str, Any]) -> str | None:
    transcription_data = payload.get("transcription_data")
    candidates = [
        transcription_data.get("transcript") if isinstance(transcription_data, dict) else None,
        payload.get("transcript"),
        payload.get("text"),
    ]
    for candidate in candidates:
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return None


def _is_final(payload: dict[str, Any]) -> bool:
    transcription_data = payload.get("transcription_data")
    if isinstance(transcription_data, dict) and "is_final" in transcription_data:
        return bool(transcription_data["is_final"])
    if "is_final" in payload:
        return bool(payload["is_final"])
    # Sin el flag no hay forma de distinguir parcial de final: preferimos
    # tratarlo como final (un turno cortado se puede corregir en el
    # siguiente; un turno que nunca llega bloquea la llamada entera).
    return True


@router.post("/webhook")
async def telnyx_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    body = await request.json()
    event = body.get("data", {})
    event_type = event.get("event_type", "")
    event_id = event.get("id")
    payload = event.get("payload", {})
    call_control_id = payload.get("call_control_id")

    if not call_control_id:
        return {"ok": True}

    if _already_processed(event_id):
        logger.info("Evento duplicado ignorado: %s id=%s call_control_id=%s", event_type, event_id, call_control_id)
        return {"ok": True}

    if event_type != "call.hangup" and _is_hung_up(call_control_id):
        logger.info("Evento tardio ignorado (llamada ya colgada): %s call_control_id=%s", event_type, call_control_id)
        return {"ok": True}

    async with get_lock(call_control_id):
        try:
            await _handle_event(event_type, payload, call_control_id, session, tenant_id)
        except Exception:
            logger.exception("Fallo procesando %s para call_control_id=%s", event_type, call_control_id)
            _cancel_watchdog(call_control_id)
            # Best-effort: intentamos despedirnos con voz en vez de dejar al
            # que llama en silencio total. Si esto tambien falla (ej. el
            # call_control_id ya no es valido), no hay mas que hacer.
            try:
                state = get_conversation_state(call_control_id, tenant_id)
                await telnyx.speak(call_control_id, ERROR_MESSAGE, interrupt=state.speaking)
                await telnyx.hangup(call_control_id)
            except Exception:
                logger.exception("Tambien fallo el intento de despedida para call_control_id=%s", call_control_id)

    return {"ok": True}


async def _handle_event(
    event_type: str,
    payload: dict[str, Any],
    call_control_id: str,
    session: AsyncSession,
    tenant_id: str,
) -> None:
    if event_type == "call.initiated" and payload.get("direction") == "incoming":
        await telnyx.answer(call_control_id)

    elif event_type == "call.answered":
        # Fase 3+: si el puente a Deepgram Voice Agent esta activo, es el
        # UNICO que maneja el turno (saluda, escucha, piensa via nuestro
        # AgentRuntime por HTTP, habla) -- saltamos por completo el flujo
        # viejo de Call Control para esta llamada. Correr los dos a la vez
        # sonaria como dos agentes hablando encima uno del otro.
        bridge_ready = is_voice_agent_bridge_ready()
        if settings.voice_agent_bridge_enabled and not bridge_ready:
            logger.error(
                "Voice Agent bridge habilitado pero incompleto; se usa Call Control como fallback. "
                "call_control_id=%s missing=%s",
                call_control_id,
                ",".join(missing_voice_agent_bridge_settings()),
            )

        if not bridge_ready:
            runtime = AgentRuntime(session, tenant_id)
            turn = await runtime.handle_turn(
                AgentMessageIn(
                    message="Hola",
                    conversation_id=call_control_id,
                    customer_phone=payload.get("from"),
                    channel="phone",
                )
            )
            state = get_conversation_state(call_control_id, tenant_id)
            state.speaking = True
            await telnyx.speak(call_control_id, turn.response)
            # Barge-in: arrancamos a escuchar YA, en paralelo con el saludo,
            # en vez de esperar a que termine de hablar. Asi el que llama
            # puede empezar a pedir mientras el agente todavia esta saludando.
            await telnyx.start_transcription(call_control_id)
            _arm_watchdog(call_control_id, tenant_id)

        # Voice Engine V2 (ver docs/06-...md): tap de audio crudo. Fase 1
        # sola = observacion pasiva, no afecta la llamada real si falla.
        # Con voice_agent_bridge_enabled tambien, Deepgram pasa a manejar
        # el turno completo (ver telephony_telnyx_stream.py).
        if settings.media_streaming_enabled and settings.public_base_url:
            stream_url = (
                settings.public_base_url.rstrip("/").replace("https://", "wss://").replace("http://", "ws://")
                + "/api/v1/telephony/telnyx/media-stream"
            )
            try:
                await telnyx.start_media_streaming(call_control_id, stream_url)
            except Exception:
                logger.exception(
                    "Media Streaming: no se pudo arrancar (no afecta la llamada real) call_control_id=%s",
                    call_control_id,
                )

    elif event_type == "call.speak.ended":
        # Limitacion conocida y aceptada: si cortamos un speak con
        # stop="current" para hablar uno nuevo, no tenemos certeza (sin
        # probarlo en una llamada real) de si Telnyx manda un solo
        # call.speak.ended para el audio final o tambien uno tardio para el
        # que cortamos. Si llega uno tardio, esto pone speaking=False
        # mientras el audio nuevo sigue sonando -- el peor caso es que el
        # SIGUIENTE barge-in no corte (el agente termina su frase en vez de
        # cortarse), no que se rompa la llamada. Se prefiere esa degradacion
        # segura a un sistema de secuencia sin validar contra Telnyx real.
        state = get_conversation_state(call_control_id, tenant_id)
        state.speaking = False
        if state.status == "closed":
            await telnyx.hangup(call_control_id)
        else:
            # La escucha ya viene corriendo desde call.answered y nunca se
            # detiene entre turnos -- aqui solo rearmamos el watchdog por si
            # el que llama se queda callado ahora que el agente ya termino.
            _arm_watchdog(call_control_id, tenant_id)

    elif event_type == "call.transcription":
        # Log completo siempre (no solo en el caso de error): es la unica
        # forma de confirmar con certeza, y no adivinando, el shape real de
        # Deepgram -- incluyendo si efectivamente llegan varios eventos
        # "parciales" por turno, que es la senal que usamos para barge-in.
        logger.info("call.transcription payload=%s", payload)

        # Llego algo del motor de voz -- hay alguien hablando, sea parcial o
        # final -- asi que el watchdog de silencio ya no aplica.
        _cancel_watchdog(call_control_id)

        if not _is_final(payload):
            return  # parcial: senal de que sigue hablando, esperamos el final

        text = _extract_transcript(payload)
        if not text:
            logger.warning("call.transcription sin texto extraible, payload=%s", payload)
            return

        state = get_conversation_state(call_control_id, tenant_id)
        state.silence_retries = 0
        was_speaking = state.speaking  # el agente seguia hablando: esto es un barge-in real

        runtime = AgentRuntime(session, tenant_id)
        turn = await runtime.handle_turn(
            AgentMessageIn(
                message=text,
                conversation_id=call_control_id,
                customer_phone=payload.get("from"),
                channel="phone",
            )
        )
        state.speaking = True
        await telnyx.speak(call_control_id, turn.response, interrupt=was_speaking)

    elif event_type == "call.hangup":
        _mark_hung_up(call_control_id)
        _cancel_watchdog(call_control_id)
        # Si el que llamaba colgó sin confirmar/cancelar/pedir un humano
        # explicitamente, AgentRuntime nunca marca la conversacion como
        # "closed" (queda en collecting/awaiting_confirmation legitimamente,
        # esperando un siguiente turno que ya no va a llegar). Sin este
        # cierre explicito, la fila en `conversations` quedaria "active"
        # para siempre -- un fantasma "en curso" en /llamadas que nunca
        # se resuelve y que ademas mantiene el auto-refresh del frontend
        # sondeando por nada.
        convo = await session.scalar(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id, Conversation.external_id == call_control_id
            )
        )
        if convo and convo.status != "closed":
            convo.status = "closed"
            if not convo.outcome:
                convo.outcome = "call.hangup"
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor="system",
                action="call.ended",
                entity_type="Call",
                entity_id=call_control_id,
                detail=f"hangup_cause={payload.get('hangup_cause', 'unknown')}",
            )
        )
        await session.commit()
        reset_conversation(call_control_id)
