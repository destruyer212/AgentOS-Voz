"""Voice Engine V2 -- puente de audio entre el WebSocket de Media Streaming
de Telnyx (`app/api/v1/telephony_telnyx_stream.py`) y el Voice Agent de
Deepgram. Deepgram maneja VAD, STT, TTS (Aura-2) y barge-in por su cuenta;
el paso "think" (decidir que responder) lo delega a nuestro propio
`AgentRuntime` via `app/api/v1/agent_llm_proxy.py`, expuesto como un
endpoint compatible con la API de Chat Completions de OpenAI.

Este modulo NO toma decisiones de negocio -- es transporte puro: recibe
audio de Telnyx, lo manda a Deepgram; recibe audio (y eventos de control)
de Deepgram, los manda a Telnyx. Validado el shape exacto de los mensajes
de "Settings" contra la API real de Deepgram antes de escribir esto (ver
docs/06-voice-engine-estado-y-brechas.md).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
from typing import Any
from urllib.parse import quote

import websockets
from fastapi import WebSocket

from app.agents.state import peek
from app.domain.text_utils import speakify_product_name
from app.infrastructure.config import settings
from app.integrations import telnyx_client as telnyx

logger = logging.getLogger(__name__)

_DEEPGRAM_VOICE_AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse"
_DEEPGRAM_SETUP_TIMEOUT_SECONDS = 12.0
_DEEPGRAM_KEEPALIVE_SECONDS = 8.0
# Respiro entre "Deepgram termino de generar el audio" (AgentAudioDone) y el
# hangup real -- el audio todavia tiene que viajar Deepgram -> nuestro
# puente -> Telnyx -> la red del que llama, asi que colgar en el instante
# exacto de AgentAudioDone corta la ultima frase de despedida antes de que
# termine de sonar del lado del cliente.
_HANGUP_GRACE_SECONDS = 2.5


async def _hangup_after_grace(call_control_id: str) -> None:
    await asyncio.sleep(_HANGUP_GRACE_SECONDS)
    try:
        await telnyx.hangup(call_control_id)
        logger.info("Voice Agent bridge: colgado automatico tras confirmar pedido call_control_id=%s", call_control_id)
    except Exception:
        # No es critico -- si falla, el que llama simplemente tiene que
        # colgar el solo. Nunca debe tumbar el resto del puente.
        logger.exception("Voice Agent bridge: fallo el colgado automatico call_control_id=%s", call_control_id)

# Aura-2, "celeste" (colombiana). Se probo "selena" (region "Latin American"
# generica) por sugerencia de la documentacion de Deepgram, pero en llamadas
# reales el usuario reporto que sonaba "rara"/"como china" -- revertido a
# celeste por pedido explicito tras escuchar ambas en vivo, priorizando
# feedback real sobre la recomendacion generica de la doc.
_SPEAK_MODEL = "aura-2-celeste-es"
# nova-3 (NO flux-general-multi). Se probo flux-general-multi hoy por su
# fin-de-turno mas rapido (<400ms, modelo semantico) pero en una llamada
# real caused dos problemas serios: (1) detecto el idioma como ingles varias
# veces sobre frases dichas en español ("Hello.", "Tomorrow." como
# transcripcion de audio en español -- confirmado en el log de esa llamada),
# y (2) el audio sonaba entrecortado ("se trababa", reportado en vivo) --
# consistente con falsos positivos de "el usuario empezo a hablar" (ruido de
# fondo detectado como voz por el modelo multilenguaje) disparando barge-in
# de mentira, que corta el audio del agente sin necesidad. nova-3 ya se
# habia probado bien en multiples llamadas reales antes de este cambio;
# revertido por evidencia real, no por preferencia. Si se quiere retomar
# Flux mas adelante, Deepgram documenta un parametro `language_hint` para
# sesgar la deteccion -- no probado todavia, quedaria para una sesion
# dedicada a validarlo antes de ponerlo en una llamada real de nuevo.
_LISTEN_MODEL = "nova-3"
# Keyterm Prompting de Deepgram (nova-3): vocabulario que el modelo no
# reconoce bien por defecto porque son palabras poco comunes en español
# general -- confirmado en vivo, cada uno de estos genero un pedido mal
# entendido real ("Mostro" -> "monstruo", "Yape" -> "yate", "Plin" -> "pli",
# "Chaufa" -> "Chaupa"). El resto de la lista son terminos propios del
# menu (nombres de plato, "Olivar" del nombre del restaurante) con la
# misma logica preventiva. Documentado en
# https://developers.deepgram.com/docs/keyterm -- 20 a 50 terminos
# recomendados, este set se queda bien por debajo de eso a proposito.
_LISTEN_KEYTERMS = [
    "El Olivar Grill",
    "Olivar",
    "Mostro",
    "Huayrito",
    "Huayro",
    "Ricky",
    "Anticucho",
    "Anticuchos",
    "Chaufa",
    "Mollejitas",
    "Huancaina",
    "Pausterizado",
    "Churrasco",
    "Costillar",
    "Chicharron",
    "Yape",
    "Plin",
]
_GREETING = f"Hola, buenas, bienvenido a {settings.restaurant_name}. ¿Qué te provoca pedir hoy?"


def _log_deepgram_event(event: dict[str, Any], call_control_id: str) -> None:
    event_type = event.get("type")
    if event_type == "Error":
        logger.error("Voice Agent bridge: error de Deepgram call_control_id=%s detail=%s", call_control_id, event)
        return
    if event_type == "Warning":
        logger.warning("Voice Agent bridge: warning de Deepgram call_control_id=%s detail=%s", call_control_id, event)
        return
    if event_type == "LatencyReport":
        logger.info("Voice Agent bridge: LatencyReport call_control_id=%s metrics=%s", call_control_id, event)
        return
    if event_type in (
        "AgentAudioDone",
        "AgentStartedSpeaking",
        "AgentThinking",
        "ConversationText",
        "History",
        "SettingsApplied",
        "Welcome",
    ):
        logger.info("Voice Agent bridge: %s call_control_id=%s", event, call_control_id)


async def _wait_for_deepgram_event(
    dg_ws,
    call_control_id: str,
    expected_type: str,
    telnyx_task: asyncio.Task,
) -> dict[str, Any]:
    deadline = time.monotonic() + _DEEPGRAM_SETUP_TIMEOUT_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Deepgram no envio {expected_type} en {_DEEPGRAM_SETUP_TIMEOUT_SECONDS:.0f}s")
        if telnyx_task.done():
            raise RuntimeError(f"Telnyx cerro el stream antes de recibir {expected_type} de Deepgram")

        recv_task = asyncio.create_task(dg_ws.recv())
        done, _ = await asyncio.wait(
            {recv_task, telnyx_task},
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if recv_task not in done:
            recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await recv_task
            if telnyx_task.done():
                raise RuntimeError(f"Telnyx cerro el stream antes de recibir {expected_type} de Deepgram")
            continue

        message = recv_task.result()
        if isinstance(message, bytes):
            logger.warning(
                "Voice Agent bridge: audio binario inesperado antes de %s call_control_id=%s bytes=%s",
                expected_type,
                call_control_id,
                len(message),
            )
            continue
        try:
            event = json.loads(message)
        except json.JSONDecodeError:
            logger.warning(
                "Voice Agent bridge: mensaje no-JSON de Deepgram antes de %s call_control_id=%s",
                expected_type,
                call_control_id,
            )
            continue

        _log_deepgram_event(event, call_control_id)
        event_type = event.get("type")
        if event_type == "Error":
            raise RuntimeError(str(event))
        if event_type == expected_type:
            return event


def missing_voice_agent_bridge_settings() -> list[str]:
    """Variables obligatorias para que el bridge pueda tomar una llamada real."""
    missing: list[str] = []
    if not settings.media_streaming_enabled:
        missing.append("MEDIA_STREAMING_ENABLED")
    if not settings.public_base_url:
        missing.append("PUBLIC_BASE_URL")
    if not settings.deepgram_api_key:
        missing.append("DEEPGRAM_API_KEY")
    return missing


def is_voice_agent_bridge_ready() -> bool:
    return settings.voice_agent_bridge_enabled and not missing_voice_agent_bridge_settings()


def _greeting_for(call_control_id: str) -> str:
    # Bug real, visto en vivo: si Telnyx reconecta el stream de audio a
    # mitad de una llamada (ej. tras un corte de red pasajero), el
    # call_control_id no cambia y el pedido en curso sigue intacto en
    # nuestro ConversationState (peek() lo confirma sin crear nada nuevo) --
    # pero Deepgram, al ser una conexion de WebSocket nueva, SIEMPRE
    # reproduce el "greeting" configurado en Settings, sin saber nada de
    # eso. El resultado sonaba como que la llamada se habia reiniciado del
    # todo y el pedido se habia perdido, cuando en realidad seguia ahi.
    state = peek(call_control_id)
    if state is not None and state.items:
        return "Seguimos aquí, se cortó un segundo. Retomamos donde íbamos: " + "; ".join(
            f"{item.quantity} {speakify_product_name(item.name)}" for item in state.items
        ) + ". ¿Seguimos con eso?"
    return _GREETING


def _build_settings(call_control_id: str, customer_phone: str | None) -> dict:
    if not settings.public_base_url:
        raise RuntimeError("PUBLIC_BASE_URL es obligatorio para Voice Agent bridge.")
    proxy_url = (
        f"{settings.public_base_url.rstrip('/')}/api/v1/agent-llm-proxy/{call_control_id}/chat/completions"
    )
    if customer_phone:
        # Bug real confirmado: el "+" de un telefono E.164 ("+51987654321")
        # sin encodear en un query string se decodifica como espacio al
        # parsear (comportamiento estandar de application/x-www-form-urlencoded,
        # que es el que usa Starlette/FastAPI para query params) -- el telefono
        # le llegaba a agent_llm_proxy.py como " 51987654321" (espacio en vez
        # de "+"), lo que rompia el match contra clientes existentes por
        # telefono (duplicaba la ficha del cliente en cada llamada).
        proxy_url += f"?customer_phone={quote(customer_phone, safe='')}"
    return {
        "type": "Settings",
        "audio": {
            "input": {"encoding": "mulaw", "sample_rate": 8000},
            "output": {"encoding": "mulaw", "sample_rate": 8000, "container": "none"},
        },
        "agent": {
            # Con nova-3 (a diferencia de Flux) SI hace falta fijar el
            # idioma explicitamente -- sin esto, nova-3 puede tambien
            # desviar a deteccion automatica. Confirmado contra la API real.
            "language": "es",
            "listen": {
                "provider": {"type": "deepgram", "model": _LISTEN_MODEL, "keyterms": _LISTEN_KEYTERMS}
            },
            # provider.type="open_ai" + un "endpoint" separado es como
            # Deepgram redirige las llamadas de "think" a un servidor propio
            # en vez del OpenAI real -- confirmado contra la API real
            # (SettingsApplied + audio real de vuelta), no es una suposicion.
            "think": {
                "provider": {"type": "open_ai", "model": "gpt-4o-mini"},
                "endpoint": {"url": proxy_url},
            },
            "speak": {"provider": {"type": "deepgram", "model": _SPEAK_MODEL}},
            "greeting": _greeting_for(call_control_id),
        },
    }


async def bridge_call(telnyx_ws: WebSocket, call_control_id: str, customer_phone: str | None) -> None:
    """Corre mientras dure la llamada. Se le entrega el control total del
    WebSocket de Telnyx una vez que llega el evento `start` (ver
    telephony_telnyx_stream.py) -- ya no hay logica de observacion pasiva
    corriendo en paralelo con esto, para evitar leer el mismo mensaje dos
    veces."""
    missing = missing_voice_agent_bridge_settings()
    if missing:
        logger.error(
            "Voice Agent bridge: configuracion incompleta call_control_id=%s missing=%s",
            call_control_id,
            ",".join(missing),
        )
        return

    headers = {"Authorization": f"Token {settings.deepgram_api_key}"}
    call_started_at = time.monotonic()
    try:
        async with websockets.connect(_DEEPGRAM_VOICE_AGENT_URL, additional_headers=headers) as dg_ws:
            logger.info(
                "Voice Agent bridge: conectado a Deepgram call_control_id=%s en %.2fs",
                call_control_id, time.monotonic() - call_started_at,
            )

            # Puerta para no mandar audio a Deepgram antes de que confirme
            # que esta listo. Bug real, visto en vivo: se mandaba Settings y
            # de inmediato se abria el reenvio de audio, sin esperar a que
            # Deepgram procesara Settings -- la doc de Deepgram marca una
            # secuencia estricta (Welcome -> Settings -> SettingsApplied ->
            # recien ahi audio) que no se estaba respetando, y en una
            # llamada real se vio una espera larga al arrancar seguida de
            # audio entrecortado, consistente con Deepgram descartando o
            # atrasando frames que llegaban en una fase invalida de la
            # conexion.
            ready = asyncio.Event()
            first_inbound_at: float | None = None
            first_outbound_at: float | None = None

            async def telnyx_to_deepgram() -> None:
                nonlocal first_inbound_at
                async for raw in telnyx_ws.iter_text():
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    event_type = event.get("event")
                    if event_type == "media":
                        if not ready.is_set():
                            continue  # Deepgram todavia no confirmo Settings -- se descarta, no se encola
                        media = event.get("media", {})
                        if media.get("track") == "inbound":
                            if first_inbound_at is None:
                                first_inbound_at = time.monotonic()
                                logger.info(
                                    "Voice Agent bridge: primer audio Telnyx->Deepgram call_control_id=%s en %.2fs",
                                    call_control_id, first_inbound_at - call_started_at,
                                )
                            await dg_ws.send(base64.b64decode(media["payload"]))
                    elif event_type == "stop":
                        logger.info("Voice Agent bridge: stop de Telnyx call_control_id=%s", call_control_id)
                        return

            telnyx_task = asyncio.create_task(telnyx_to_deepgram())

            try:
                await _wait_for_deepgram_event(dg_ws, call_control_id, "Welcome", telnyx_task)
                await dg_ws.send(json.dumps(_build_settings(call_control_id, customer_phone)))
                logger.info("Voice Agent bridge: Settings enviado call_control_id=%s", call_control_id)
                await _wait_for_deepgram_event(dg_ws, call_control_id, "SettingsApplied", telnyx_task)
            except (TimeoutError, RuntimeError) as exc:
                logger.error(
                    "Voice Agent bridge: no se pudo preparar la sesion de Deepgram call_control_id=%s error=%s",
                    call_control_id, exc,
                )
                telnyx_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await telnyx_task
                return

            ready.set()
            logger.info(
                "Voice Agent bridge: listo para audio call_control_id=%s en %.2fs",
                call_control_id, time.monotonic() - call_started_at,
            )

            async def keepalive_loop() -> None:
                # Bug real, visto en vivo: el que llama se queda pensando
                # unos segundos entre frases (ej. respondiendo "recojo en
                # el local o delivery?") y Telnyx, con supresion de
                # silencio, deja de mandar frames de audio mientras tanto.
                # Deepgram tiene su PROPIO timeout de inactividad del lado
                # del cliente ("we did not receive audio within our
                # timeout", CLIENT_MESSAGE_TIMEOUT) que cierra la conexion
                # si no le llega NADA en un rato -- sin este keepalive, eso
                # tumbaba el puente entero a mitad de un pedido en curso, y
                # Telnyx reconectaba el stream desde cero, reiniciando la
                # conversacion con el saludo de nuevo ("volvio al inicio",
                # reportado en vivo con el pedido ya armado). El mensaje
                # "KeepAlive" de Deepgram cuenta como actividad sin ser
                # audio real, asi que evita el timeout sin interferir con
                # el audio de verdad.
                while True:
                    await asyncio.sleep(_DEEPGRAM_KEEPALIVE_SECONDS)
                    try:
                        await dg_ws.send(json.dumps({"type": "KeepAlive"}))
                    except websockets.exceptions.ConnectionClosed:
                        # El otro lado ya se encarga de cerrar el puente
                        # entero (deepgram_to_telnyx lo detecta); este loop
                        # no tiene nada mas que hacer.
                        return

            hangup_triggered = False

            async def deepgram_to_telnyx() -> None:
                nonlocal first_outbound_at, hangup_triggered
                async for message in dg_ws:
                    if isinstance(message, bytes):
                        if first_outbound_at is None:
                            first_outbound_at = time.monotonic()
                            logger.info(
                                "Voice Agent bridge: primer audio Deepgram->Telnyx call_control_id=%s en %.2fs",
                                call_control_id, first_outbound_at - call_started_at,
                            )
                        await telnyx_ws.send_text(json.dumps({
                            "event": "media",
                            "media": {"payload": base64.b64encode(message).decode()},
                        }))
                        continue
                    try:
                        event = json.loads(message)
                    except json.JSONDecodeError:
                        continue
                    event_type = event.get("type")
                    if event_type == "UserStartedSpeaking":
                        # Barge-in real: el que llama empezo a hablar, cortar
                        # de inmediato lo que Telnyx estuviera reproduciendo.
                        await telnyx_ws.send_text(json.dumps({"event": "clear"}))
                    else:
                        _log_deepgram_event(event, call_control_id)
                        if event_type == "AgentAudioDone" and not hangup_triggered:
                            # Bug real, reportado en vivo: tras confirmar el
                            # pedido ("Listo, pedido confirmado... ¡Gracias!"),
                            # la llamada se quedaba conectada indefinidamente
                            # -- el flujo viejo de Call Control colgaba en
                            # call.speak.ended si el estado quedaba "closed",
                            # pero este puente nuevo nunca reproduce ese
                            # evento (Deepgram maneja el audio por su cuenta),
                            # asi que ese colgado automatico nunca se
                            # disparaba. AgentAudioDone es la señal equivalente
                            # aca: "termine de reproducir la respuesta de este
                            # turno". Si en ese momento el pedido ya quedo
                            # confirmado, colgamos -- pero solo la PRIMERA vez
                            # (Deepgram puede mandar varios AgentAudioDone
                            # seguidos si la respuesta salio en varios
                            # fragmentos de TTS).
                            state = peek(call_control_id)
                            if state is not None and state.hangup_after_response:
                                hangup_triggered = True
                                asyncio.create_task(_hangup_after_grace(call_control_id))

            done, pending = await asyncio.wait(
                [telnyx_task, asyncio.create_task(deepgram_to_telnyx()), asyncio.create_task(keepalive_loop())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            # Sin esto, si Deepgram cierra la conexion con un error (ej. el
            # FAILED_TO_THINK visto en vivo), la excepcion queda "sin
            # retirar" -- asyncio.wait() NO la relanza sola, solo devuelve
            # la tarea ya terminada. El sintoma real: "Task exception was
            # never retrieved" en el log, y sin loguear la causa real.
            for task in done:
                exc = task.exception()
                if exc:
                    logger.error(
                        "Voice Agent bridge: una tarea del puente termino con error call_control_id=%s error=%r",
                        call_control_id, exc,
                    )
            # Cancelar la tarea que sigue viva no es instantaneo -- hay que
            # esperarla para que termine de verdad antes de cerrar el
            # WebSocket de Deepgram (el `async with` de arriba lo hace al
            # salir de este bloque). Sin este await, quedaba "pendiente" en
            # segundo plano sin garantia de haber parado a tiempo.
            for task in pending:
                task.cancel()
            for task in pending:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    except Exception:
        logger.exception("Voice Agent bridge: fallo inesperado call_control_id=%s", call_control_id)
