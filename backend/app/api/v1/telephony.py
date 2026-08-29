"""Webhooks de Twilio Voice (Sprint 7: telefonia real).

Reutiliza exactamente el mismo cerebro que /agent/turn (AgentRuntime): la
llamada telefonica es solo un canal mas de entrada, igual que el chat web.
El `CallSid` de Twilio se usa directamente como `conversation_id`, asi que
el estado de la conversacion es el mismo objeto en memoria sin importar si
el turno llego por HTTP JSON o por un webhook de voz.

Flujo:
  Twilio recibe una llamada -> POST /voice/incoming (saludo + primer Gather)
  Twilio transcribe la respuesta -> POST /voice/turn (repite hasta cerrar)
  Twilio notifica el fin de la llamada -> POST /voice/status (limpieza + auditoria)

Seguridad: Twilio firma cada webhook con `X-Twilio-Signature`. La
validacion esta implementada (`verify_twilio_signature`) pero queda
deshabilitada por defecto (`TWILIO_VERIFY_SIGNATURE=false`): activarla mal
detras de un tunel/proxy que no reescribe bien el host puede tumbar TODAS
las llamadas reales con 403 silenciosos, que es peor que no validar en un
entorno de desarrollo. Activarla explicitamente en produccion.
"""

import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import Gather, VoiceResponse

from app.agents.runtime import AgentRuntime
from app.agents.state import get_lock
from app.agents.state import reset as reset_conversation
from app.api.deps import get_db, get_tenant_id
from app.domain.models import AuditLog, Conversation
from app.domain.schemas import AgentMessageIn
from app.domain.services import ProductService
from app.infrastructure.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telephony", tags=["telephony"])

NO_INPUT_MESSAGE = "No escuché nada. Llama de nuevo cuando quieras, ¡chau!"
ERROR_MESSAGE = "Tuvimos un problema técnico. Intenta llamar en un momento."


def _error_response() -> Response:
    """Ultimo recurso si algo revienta a mitad de la llamada: preferimos
    despedirnos con voz y colgar en vez de dejar al que llama en silencio
    total con un 500 crudo que Twilio no sabe traducir a audio."""
    vr = VoiceResponse()
    vr.say(ERROR_MESSAGE, language=settings.agent_voice_language)
    vr.hangup()
    return Response(content=str(vr), media_type="application/xml")


async def verify_twilio_signature(request: Request) -> None:
    if not settings.twilio_verify_signature or not settings.twilio_auth_token:
        return
    validator = RequestValidator(settings.twilio_auth_token)
    signature = request.headers.get("X-Twilio-Signature", "")
    form = await request.form()
    if not validator.validate(str(request.url), dict(form), signature):
        raise HTTPException(status_code=403, detail="Firma de Twilio invalida.")


async def _speech_hints(session: AsyncSession, tenant_id: str) -> str:
    """Nombres del catalogo como pistas para el reconocimiento de voz de
    Twilio: mejora bastante la precision en productos con nombre propio
    ("Inca Kola") que un ASR generico no adivina bien."""
    products = await ProductService(session, tenant_id).list_all()
    names = [p.name for p in products]
    extra = ["si", "no", "confirmo", "cancelar", "hablar con una persona"]
    return ", ".join(names + extra)


def _gather_response(prompt: str, hints: str) -> Response:
    vr = VoiceResponse()
    gather = Gather(
        input="speech",
        action="/api/v1/telephony/voice/turn",
        method="POST",
        language=settings.agent_voice_language,
        speech_timeout="auto",
        hints=hints or None,
    )
    gather.say(prompt, language=settings.agent_voice_language)
    vr.append(gather)
    vr.say(NO_INPUT_MESSAGE, language=settings.agent_voice_language)
    return Response(content=str(vr), media_type="application/xml")


@router.post("/voice/incoming", dependencies=[Depends(verify_twilio_signature)])
async def voice_incoming(
    CallSid: str = Form(...),
    From: str = Form(""),
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> Response:
    try:
        async with get_lock(CallSid):
            runtime = AgentRuntime(session, tenant_id)
            turn = await runtime.handle_turn(
                AgentMessageIn(message="Hola", conversation_id=CallSid, customer_phone=From or None, channel="phone")
            )
            hints = await _speech_hints(session, tenant_id)
            return _gather_response(turn.response, hints)
    except Exception:
        logger.exception("Fallo procesando voice/incoming para CallSid=%s", CallSid)
        return _error_response()


@router.post("/voice/turn", dependencies=[Depends(verify_twilio_signature)])
async def voice_turn(
    CallSid: str = Form(...),
    From: str = Form(""),
    SpeechResult: str = Form(""),
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> Response:
    try:
        async with get_lock(CallSid):
            hints = await _speech_hints(session, tenant_id)

            if not SpeechResult.strip():
                return _gather_response("No te escuché bien, ¿qué decías?", hints)

            runtime = AgentRuntime(session, tenant_id)
            turn = await runtime.handle_turn(
                AgentMessageIn(message=SpeechResult, conversation_id=CallSid, customer_phone=From or None, channel="phone")
            )

            if turn.status == "closed":
                vr = VoiceResponse()
                vr.say(turn.response, language=settings.agent_voice_language)
                vr.hangup()
                reset_conversation(CallSid)
                return Response(content=str(vr), media_type="application/xml")

            return _gather_response(turn.response, hints)
    except Exception:
        logger.exception("Fallo procesando voice/turn para CallSid=%s", CallSid)
        return _error_response()


@router.post("/voice/status", dependencies=[Depends(verify_twilio_signature)])
async def voice_status(
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: str | None = Form(None),
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    if CallStatus in {"completed", "busy", "failed", "no-answer", "canceled"}:
        # Igual que en Telnyx: si colgaron sin llegar a un cierre explicito
        # del agente (confirmar/cancelar/pedir humano), la conversacion se
        # queda "active" en la DB para siempre si no la cerramos aqui.
        convo = await session.scalar(
            select(Conversation).where(Conversation.tenant_id == tenant_id, Conversation.external_id == CallSid)
        )
        if convo and convo.status != "closed":
            convo.status = "closed"
            if not convo.outcome:
                convo.outcome = "call.ended"
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor="system",
                action="call.ended",
                entity_type="Call",
                entity_id=CallSid,
                detail=f"status={CallStatus} duration={CallDuration or '0'}s",
            )
        )
        await session.commit()
        reset_conversation(CallSid)
    return {"ok": True}
