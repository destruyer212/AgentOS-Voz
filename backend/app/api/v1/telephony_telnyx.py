"""Webhook unico de Telnyx Call Control v2 (Sprint 7, alternativa a Twilio).

Igual que la integracion de Twilio, esto es solo transporte: el cerebro
sigue siendo `AgentRuntime`, el mismo que atiende el chat web. La
diferencia es el modelo de control: Twilio responde TwiML en el propio
request; Telnyx manda eventos async y nosotros reaccionamos con comandos
REST (`app/integrations/telnyx_client.py`).

Flujo (`call_control_id` de Telnyx = `conversation_id` del runtime):

  call.initiated (incoming)  -> answer()
  call.answered              -> primer turno del AgentRuntime -> speak(saludo)
  call.speak.ended           -> si el turno anterior cerro: hangup()
                                 si no: start_transcription() (escucha al que llama)
  call.transcription         -> turno del AgentRuntime con el texto -> speak(respuesta)
  call.hangup                -> limpieza + auditoria

ADVERTENCIA HONESTA: el shape exacto del payload de `call.transcription`
(donde viene el texto y el flag de "segmento completo") no esta
documentado publicamente con certeza al momento de escribir esto, y no se
pudo probar contra una llamada real desde este entorno. `_extract_transcript`
prueba varias rutas conocidas y loguea el payload completo si no encuentra
texto, para poder ajustarlo rapido apenas llegue el primer evento real.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import AgentRuntime
from app.agents.state import get_lock
from app.agents.state import get_or_create as get_conversation_state
from app.agents.state import reset as reset_conversation
from app.api.deps import get_db, get_tenant_id
from app.domain.models import AuditLog
from app.domain.schemas import AgentMessageIn
from app.integrations import telnyx_client as telnyx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telephony/telnyx", tags=["telephony-telnyx"])

ERROR_MESSAGE = "Tuvimos un problema tecnico. Por favor intenta llamar de nuevo en un momento."


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
    payload = event.get("payload", {})
    call_control_id = payload.get("call_control_id")

    if not call_control_id:
        return {"ok": True}

    async with get_lock(call_control_id):
        try:
            await _handle_event(event_type, payload, call_control_id, session, tenant_id)
        except Exception:
            logger.exception("Fallo procesando %s para call_control_id=%s", event_type, call_control_id)
            # Best-effort: intentamos despedirnos con voz en vez de dejar al
            # que llama en silencio total. Si esto tambien falla (ej. el
            # call_control_id ya no es valido), no hay mas que hacer.
            try:
                await telnyx.speak(call_control_id, ERROR_MESSAGE)
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
        runtime = AgentRuntime(session, tenant_id)
        turn = await runtime.handle_turn(
            AgentMessageIn(
                message="Hola",
                conversation_id=call_control_id,
                customer_phone=payload.get("from"),
            )
        )
        await telnyx.speak(call_control_id, turn.response)

    elif event_type == "call.speak.ended":
        state = get_conversation_state(call_control_id, tenant_id)
        if state.status == "closed":
            await telnyx.hangup(call_control_id)
        else:
            await telnyx.start_transcription(call_control_id)

    elif event_type == "call.transcription":
        if not _is_final(payload):
            return

        text = _extract_transcript(payload)
        if not text:
            logger.warning("call.transcription sin texto extraible, payload=%s", payload)
            return

        await telnyx.stop_transcription(call_control_id)

        runtime = AgentRuntime(session, tenant_id)
        turn = await runtime.handle_turn(
            AgentMessageIn(
                message=text,
                conversation_id=call_control_id,
                customer_phone=payload.get("from"),
            )
        )
        await telnyx.speak(call_control_id, turn.response)

    elif event_type == "call.hangup":
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
