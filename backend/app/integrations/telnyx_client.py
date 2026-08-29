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
        if response.status_code >= 400:
            logger.error("Telnyx %s fallo (%s): %s", command, response.status_code, response.text)
        response.raise_for_status()


async def answer(call_control_id: str) -> None:
    await _command(call_control_id, "answer", {})


async def speak(call_control_id: str, text: str, *, interrupt: bool = False) -> None:
    # Confirmado en vivo (error 90013 de Telnyx): service_level="basic" solo
    # acepta voice="male"/"female" con language="en-US" -- ingles nada mas.
    # Para espanol hace falta service_level="premium" con una voz explicita
    # en formato Provider.Model.VoiceId; la propia voz ya define el idioma,
    # asi que no se manda "language" aqui (ese campo es lo que fallaba).
    #
    # interrupt=True (barge-in): corta lo que el agente estuviera diciendo
    # ("stop": "current", validado contra la API real) y arranca este audio
    # de inmediato. Se usa cuando el que llama termino de hablar mientras
    # el agente todavia seguia con la respuesta anterior.
    body = {
        "payload": text,
        "voice": "AWS.Polly.Lupe-Neural",
        "service_level": "premium",
        "payload_type": "text",
    }
    if interrupt:
        body["stop"] = "current"
    await _command(call_control_id, "speak", body)


async def start_transcription(call_control_id: str) -> None:
    # Deepgram Nova-3, no Google: es el motor que la industria de voice-AI
    # en tiempo real usa especificamente por su latencia baja (Google es
    # generico, pensado para transcribir video/grabaciones, no para
    # conversacion en vivo). Validado el formato del body contra la API
    # real antes de subir esto (mismo tipo de bug que ya nos mordio una vez
    # con "language" mal ubicado: aqui SI va en transcription_engine_config,
    # igual que con Google).
    await _command(
        call_control_id,
        "transcription_start",
        {
            "transcription_engine": "Deepgram",
            "transcription_engine_config": {
                "transcription_engine": "Deepgram",
                "transcription_model": "deepgram/nova-3",
                "language": "es",
                "smart_format": True,  # formatea numeros/horas ("las ocho" -> mejor detectado como hora)
                # Barge-in: con esto Deepgram manda eventos intermedios
                # mientras el que llama sigue hablando, no solo al terminar.
                # Los usamos para saber que hay alguien hablando -- el corte
                # real del agente pasa cuando llega el evento final (ver
                # app/api/v1/telephony_telnyx.py).
                "interim_results": True,
                # Deepgram declara "el usuario termino de hablar" tras esta
                # pausa de silencio -- esto es tiempo muerto real que el que
                # llama espera ANTES de que el agente empiece a procesar, en
                # cada turno, sin excepcion. Se habia subido a 1800ms para
                # evitar que una pausa natural a media frase ("quiero una
                # hamburguesa... sin lechuga") se cortara en dos turnos. Pero
                # medido en llamadas reales, eso sumaba ~1.8s de silencio fijo
                # ENCIMA de los ~1.5-2.4s que ya toma nuestro propio
                # procesamiento (Gemini + logica) -- mas de 3s de silencio
                # total antes de que el agente respondiera, y eso es lo que
                # se percibe como lento.
                # Bajado a 1000ms (el default de Deepgram) porque el riesgo
                # que motivo subirlo ya no es tan grave: el rediseño de
                # deteccion de "esto responde lo pendiente vs. es una edicion"
                # (ver runtime.py _handle_detail_answer) y el manejo de items
                # ambiguos ya toleran mucho mejor un corte a mitad de frase --
                # si el fragmento queda incompleto, el siguiente turno lo
                # completa en vez de perderse o corromper un dato.
                "utterance_end_ms": 1000,
            },
            "transcription_tracks": "inbound",
        },
    )


async def start_media_streaming(call_control_id: str, stream_url: str) -> None:
    """Voice Engine V2, Fase 1: arranca el streaming de audio crudo (RTP,
    base64) de la llamada hacia nuestro propio WebSocket, en paralelo a todo
    lo que ya hace Call Control (answer/speak/transcription_start). No
    reemplaza nada del flujo actual -- es un tap adicional sobre el audio.

    stream_bidirectional_mode="mp3": para cuando en una fase posterior le
    mandemos audio de vuelta (TTS propio), Telnyx acepta directamente un mp3
    en base64 sin que tengamos que codificar RTP/PCMU nosotros mismos.
    Validado el shape exacto de este body contra la documentacion oficial
    de Telnyx antes de usarlo (misma disciplina que con transcription_start:
    nunca adivinar el nombre/ubicacion de un parametro nuevo).
    """
    await _command(
        call_control_id,
        "streaming_start",
        {
            "stream_url": stream_url,
            "stream_track": "both_tracks",
            # rtp/PCMU (no mp3): asi el audio que nos manda Deepgram Voice
            # Agent (mulaw/8000 crudo, ver voice_agent_bridge.py) se puede
            # reenviar a Telnyx byte por byte, sin transcodificar nada --
            # PCMU es el mismo codec que "mulaw", solo cambia el nombre
            # entre proveedores.
            "stream_bidirectional_mode": "rtp",
            "stream_bidirectional_codec": "PCMU",
            "stream_bidirectional_target_legs": "self",
        },
    )


async def stop_transcription(call_control_id: str) -> None:
    await _command(call_control_id, "transcription_stop", {})


async def hangup(call_control_id: str) -> None:
    await _command(call_control_id, "hangup", {})
