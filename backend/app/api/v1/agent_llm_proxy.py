"""Voice Engine V2 -- puente "think" para el Voice Agent de Deepgram.

Deepgram orquesta VAD, STT y TTS (Aura-2) por su cuenta; el unico paso que
delega afuera es "think" (decidir que responder), y lo hace hablando con
CUALQUIER endpoint compatible con la API de Chat Completions de OpenAI
(`POST {url}` con `{"messages": [...], "stream": bool}`, respuesta en el
formato `chat.completion` estandar). Eso es EXACTAMENTE lo que exponemos
aca -- no un LLM generico, sino un envoltorio fino sobre el `AgentRuntime`
real (el mismo que atiende chat web y el flujo actual de Telnyx Call
Control): mismo catalogo, mismo stock, mismos pedidos, misma DB. Deepgram
nunca toca el negocio directamente, solo nos manda texto y espera texto.

Por que un endpoint por-llamada (`/{call_control_id}/chat/completions`) y
no un unico endpoint generico: el formato de Chat Completions no tiene
concepto de "conversation_id" propio, y nuestro estado de conversacion
(`ConversationState`) es por `call_control_id`. Incrustamos el
call_control_id (y el telefono del que llama) en la URL que le pasamos a
Deepgram al arrancar la sesion (ver `voice_agent_bridge.py`), asi cada
llamada activa habla con su propio "hilo" sin tener que re-parsear el
historial completo de mensajes en cada turno.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

_ERROR_FALLBACK_TEXT = "Tuvimos un problema técnico. ¿Puedes repetir eso?"

from app.agents.runtime import AgentRuntime
from app.agents.state import get_lock, is_hung_up
from app.api.deps import get_db, get_tenant_id
from app.domain.schemas import AgentMessageIn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent-llm-proxy", tags=["voice-engine-v2"])


def _extract_last_user_message(messages: list[dict]) -> str | None:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return None


async def _chat_completion_stream(text: str, model: str) -> AsyncIterator[str]:
    """Formato SSE de streaming de OpenAI (chat.completion.chunk). Nuestra
    respuesta ya esta completa cuando llegamos aca (AgentRuntime no genera
    token por token), asi que se manda como un unico "delta" seguido del
    chunk final -- no gana velocidad real, pero es el formato que el cliente
    de Deepgram espera cuando pide `stream: true` (confirmado en vivo: sin
    esto, Deepgram reportaba "Failed to think" pese a que este endpoint
    respondia 200 con contenido correcto)."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    delta_chunk = {
        "id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}],
    }
    final_chunk = {
        "id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(delta_chunk, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


def _chat_completion_response(text: str, model: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@router.post("/{call_control_id}/chat/completions", response_model=None)
async def agent_llm_proxy(
    call_control_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> dict | StreamingResponse:
    # Defaults fuera del try: si algo revienta antes de leer el body (JSON
    # malformado, por ejemplo), igual necesitamos "model"/"stream" validos
    # para devolver una respuesta bien formada en vez de un 500 crudo.
    model = "agentos-voz"
    stream = False
    try:
        body = await request.json()
        messages = body.get("messages", [])
        model = body.get("model") or "agentos-voz"
        stream = bool(body.get("stream", False))
        customer_phone = request.query_params.get("customer_phone") or None

        # Llamada ya colgada: call.hangup ya se proceso y ya limpio el
        # ConversationState (ver app/agents/state.py, registro compartido con
        # telephony_telnyx.py). Esto pasa cuando Deepgram todavia estaba
        # terminando de "pensar" el ultimo turno justo cuando el que llama
        # colgo. Sin este chequeo, get_or_create() crea un estado nuevo en
        # blanco y _persist_conversation() reabre en la DB ("active") una
        # conversacion que el hangup ya habia cerrado -- una llamada fantasma
        # que vuelve a aparecer como en curso despues de haber terminado.
        if is_hung_up(call_control_id):
            logger.info(
                "agent-llm-proxy: request tardio ignorado (llamada ya colgada) call_control_id=%s",
                call_control_id,
            )
            text = ""
        else:
            user_text = _extract_last_user_message(messages)
            if not user_text:
                # Deepgram a veces manda un "kickoff" sin mensaje de usuario todavia
                # (ej. para que el agente hable primero). No hay nada que procesar
                # via AgentRuntime en ese caso -- una respuesta vacia es valida.
                logger.info("agent-llm-proxy: sin mensaje de usuario, respuesta vacia call_control_id=%s", call_control_id)
                text = ""
            else:
                # Deepgram puede mandar turnos casi simultaneos si el que llama
                # habla en frases cortadas (ej. "Calle" y "UTP" como dos finales
                # seguidos). Sin este lock, dos requests concurrentes pueden
                # pisarse el mismo ConversationState -- visto en vivo: una
                # direccion quedo incompleta porque el segundo fragmento se
                # proceso antes de que el primero terminara de aplicarse. El
                # flujo viejo de Telnyx Call Control ya usaba este mismo lock
                # por conversation_id; aca faltaba.
                async with get_lock(call_control_id):
                    runtime = AgentRuntime(session, tenant_id)
                    turn = await runtime.handle_turn(
                        AgentMessageIn(
                            message=user_text,
                            conversation_id=call_control_id,
                            customer_phone=customer_phone,
                            channel="phone",
                        )
                    )
                text = turn.response
                logger.info(
                    "agent-llm-proxy: call_control_id=%s intent=%s status=%s stream=%s user=%r response=%r",
                    call_control_id, turn.intent, turn.status, stream, user_text, text,
                )
    except Exception:
        # Red de seguridad: sin esto, CUALQUIER excepcion aca (body sin JSON
        # valido, "messages" con una forma inesperada, el timeout de Gemini
        # que ya tiene su propio fallback interno, lo que sea) devuelve un
        # 500 crudo a Deepgram, que lo reporta como "Failed to think" y mata
        # la sesion -- Telnyx la reconecta desde cero y el que llama escucha
        # el saludo de nuevo, perdiendo el hilo. Mejor una disculpa hablada
        # que silencio o un reinicio. Antes este try/except solo envolvia la
        # llamada a AgentRuntime; un body malformado se escapaba sin capturar.
        logger.exception(
            "agent-llm-proxy: fallo inesperado procesando el request call_control_id=%s",
            call_control_id,
        )
        text = _ERROR_FALLBACK_TEXT

    if stream:
        return StreamingResponse(_chat_completion_stream(text, model), media_type="text/event-stream")
    return _chat_completion_response(text, model)
