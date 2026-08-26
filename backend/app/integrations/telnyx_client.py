"""Cliente delgado de comandos de Call Control v2 de Telnyx.

A diferencia de Twilio (que responde con TwiML sincrono en el mismo
request), Telnyx funciona por eventos: Telnyx nos avisa por webhook que
algo paso en la llamada, y nosotros reaccionamos llamando estos comandos
REST por separado. Ver `app/api/v1/telephony_telnyx.py` para el flujo
completo.
"""

from __future__ import annotations

import logging

import httpx

from app.infrastructure.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.telnyx.com/v2"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.telnyx_api_key}",
        "Content-Type": "application/json",
    }


async def _command(call_control_id: str, command: str, body: dict) -> None:
    if settings.telnyx_dry_run:
        # Permite probar toda la logica del webhook (secuencia de comandos,
        # turnos del agente) sin una llamada real ni gastar API calls.
        logger.info("[telnyx dry-run] %s call=%s body=%s", command, call_control_id, body)
        return
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{_BASE_URL}/calls/{call_control_id}/actions/{command}",
            headers=_headers(),
            json=body,
        )
        response.raise_for_status()


async def answer(call_control_id: str) -> None:
    await _command(call_control_id, "answer", {})


async def speak(call_control_id: str, text: str) -> None:
    # service_level="basic" + voice="female" es la combinacion mas segura
    # sin poder verificar en vivo que voice IDs premium (Provider.Model.Voice)
    # estan disponibles en esta cuenta.
    await _command(
        call_control_id,
        "speak",
        {
            "payload": text,
            "voice": "female",
            "service_level": "basic",
            "language": settings.agent_voice_language,
            "payload_type": "text",
        },
    )


async def start_transcription(call_control_id: str) -> None:
    await _command(
        call_control_id,
        "transcription_start",
        {
            "language": settings.agent_voice_language,
            "transcription_engine": "Google",
            "transcription_tracks": "inbound",
        },
    )


async def stop_transcription(call_control_id: str) -> None:
    await _command(call_control_id, "transcription_stop", {})


async def hangup(call_control_id: str) -> None:
    await _command(call_control_id, "hangup", {})
