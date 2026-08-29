"""Voice Engine V2 -- Fase 1: receptor del WebSocket de Media Streaming de
Telnyx (audio crudo, bidireccional). Ver docs/06-voice-engine-estado-y-brechas.md
para el plan completo de fases.

IMPORTANTE: este endpoint NO maneja la conversacion todavia. Es un tap
adicional sobre el audio, en paralelo al flujo real (`telephony_telnyx.py`,
Call Control), que sigue siendo el que contesta/habla/transcribe la llamada
real. El objetivo de esta fase es validar, contra una llamada real, que:

  1. Telnyx efectivamente conecta a este WebSocket cuando se pide
     `streaming_start` (ver `telnyx_client.start_media_streaming`).
  2. El shape de los eventos (`start`/`media`/`stop`/`dtmf`) es el
     documentado -- la disciplina de este proyecto es siempre confirmar el
     shape real antes de construir logica encima (nos mordio mas de una vez
     asumir mal un shape de Telnyx).
  3. La latencia/orden de los frames de audio es la esperada.

Nada de esto se activa a menos que `MEDIA_STREAMING_ENABLED=true` -- ver
`call.answered` en `telephony_telnyx.py`.
"""

from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.infrastructure.config import settings
from app.integrations.voice_agent_bridge import (
    bridge_call,
    is_voice_agent_bridge_ready,
    missing_voice_agent_bridge_settings,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telephony/telnyx", tags=["telephony-telnyx-stream"])


class _StreamStats:
    """Contadores minimos por conexion para no inundar el log con un
    mensaje por cada frame de audio (llegan muy seguido, 20-30ms cada uno)."""

    __slots__ = ("call_control_id", "inbound_frames", "media_format", "outbound_frames", "started_at", "stream_id")

    def __init__(self) -> None:
        self.stream_id: str | None = None
        self.call_control_id: str | None = None
        self.media_format: dict | None = None
        self.inbound_frames = 0
        self.outbound_frames = 0
        self.started_at = time.monotonic()


@router.websocket("/media-stream")
async def media_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    stats = _StreamStats()
    logger.info("Media Streaming: conexion WebSocket aceptada")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Media Streaming: mensaje no-JSON recibido, ignorado")
                continue

            event_type = event.get("event")

            if event_type == "connected":
                logger.info("Media Streaming: connected version=%s", event.get("version"))

            elif event_type == "start":
                start_data = event.get("start", {})
                stats.stream_id = event.get("stream_id")
                stats.call_control_id = start_data.get("call_control_id")
                stats.media_format = start_data.get("media_format")
                logger.info(
                    "Media Streaming: start stream_id=%s call_control_id=%s media_format=%s",
                    stats.stream_id, stats.call_control_id, stats.media_format,
                )

                if settings.voice_agent_bridge_enabled and stats.call_control_id:
                    if not is_voice_agent_bridge_ready():
                        logger.error(
                            "Voice Agent bridge habilitado pero incompleto; el stream queda en modo observacion. "
                            "call_control_id=%s missing=%s",
                            stats.call_control_id,
                            ",".join(missing_voice_agent_bridge_settings()),
                        )
                        continue
                    # Fase 3+: a partir de aca, el puente pasa a leer el
                    # WebSocket el mismo (websocket.iter_text() dentro de
                    # bridge_call) -- este bucle de observacion pasiva no
                    # debe seguir consumiendo mensajes en paralelo, o se
                    # roban eventos entre si. Por eso se sale del bucle
                    # despues, en vez de seguir al "elif media".
                    customer_phone = start_data.get("from")
                    await bridge_call(websocket, stats.call_control_id, customer_phone)
                    logger.info(
                        "Voice Agent bridge: terminado call_control_id=%s", stats.call_control_id
                    )
                    return

            elif event_type == "media":
                media = event.get("media", {})
                track = media.get("track")
                if track == "inbound":
                    stats.inbound_frames += 1
                else:
                    stats.outbound_frames += 1
                # Un log por frame seria ruido puro (20-30ms cada uno) --
                # solo confirmamos que siguen llegando cada ~100 frames.
                total = stats.inbound_frames + stats.outbound_frames
                if total % 100 == 0:
                    elapsed = time.monotonic() - stats.started_at
                    logger.info(
                        "Media Streaming: %s frames en %.1fs (inbound=%s outbound=%s) call_control_id=%s",
                        total, elapsed, stats.inbound_frames, stats.outbound_frames, stats.call_control_id,
                    )

            elif event_type == "dtmf":
                logger.info(
                    "Media Streaming: dtmf digit=%s call_control_id=%s",
                    event.get("dtmf", {}).get("digit"), stats.call_control_id,
                )

            elif event_type == "stop":
                logger.info(
                    "Media Streaming: stop call_control_id=%s total_inbound=%s total_outbound=%s",
                    stats.call_control_id, stats.inbound_frames, stats.outbound_frames,
                )
                break

            else:
                logger.warning("Media Streaming: evento desconocido event=%s", event_type)

    except WebSocketDisconnect:
        logger.info(
            "Media Streaming: WebSocket desconectado call_control_id=%s total_inbound=%s total_outbound=%s",
            stats.call_control_id, stats.inbound_frames, stats.outbound_frames,
        )
    except Exception:
        logger.exception("Media Streaming: error inesperado procesando el stream")
