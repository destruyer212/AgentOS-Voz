"""Corte automatico de llamadas colgadas / con ruido de fondo sin pedido
real (ver app/integrations/voice_agent_bridge.py, _watchdog_decision +
_silence_and_duration_watchdog). Telnyx cobra por minuto sin importar si
hay una conversacion real pasando -- una llamada que nadie corta (el
cliente se olvida, o hay gente hablando cerca del telefono sin pedir nada)
sigue generando costo indefinidamente si no se corta sola.

La logica de decision (_watchdog_decision) es pura -- se testea con
valores de tiempo exactos, sin esperar milisegundos reales (eso es lo que
antes volvia estos tests flaky). Un solo test de humo cubre el loop async
que la envuelve, con margenes de tiempo bien holgados."""

import asyncio
import json
import time

import pytest

from app.agents.state import get_or_create, reset
from app.infrastructure.config import settings
from app.integrations import voice_agent_bridge as bridge


@pytest.fixture(autouse=True)
def _watchdog_thresholds():
    original_warning = settings.call_silence_warning_seconds
    original_grace = settings.call_silence_hangup_grace_seconds
    original_max_duration = settings.call_max_duration_seconds
    settings.call_silence_warning_seconds = 30
    settings.call_silence_hangup_grace_seconds = 15
    settings.call_max_duration_seconds = 600
    yield
    settings.call_silence_warning_seconds = original_warning
    settings.call_silence_hangup_grace_seconds = original_grace
    settings.call_max_duration_seconds = original_max_duration


def test_no_action_with_recent_activity_and_no_prior_warning():
    action, warned_at = bridge._watchdog_decision(
        now=100.0, call_started_at=0.0, last_activity=95.0, warned_at=None
    )
    assert action == "none"
    assert warned_at is None


def test_warns_once_silence_crosses_the_warning_threshold():
    # last_activity=0, now=31 -> 31s de silencio, mas que
    # call_silence_warning_seconds=30.
    action, warned_at = bridge._watchdog_decision(
        now=31.0, call_started_at=0.0, last_activity=0.0, warned_at=None
    )
    assert action == "warn"
    assert warned_at == 31.0  # el momento del aviso, para medir la gracia desde ahi


def test_no_hangup_yet_right_after_the_warning():
    action, warned_at = bridge._watchdog_decision(
        now=32.0, call_started_at=0.0, last_activity=0.0, warned_at=31.0
    )
    assert action == "none"
    assert warned_at == 31.0


def test_hangs_up_after_grace_period_past_the_warning():
    # warned_at=31, grace=15 -> cuelga pasado el segundo 46.
    action, _ = bridge._watchdog_decision(
        now=47.0, call_started_at=0.0, last_activity=0.0, warned_at=31.0
    )
    assert action == "hangup_silence"


def test_real_activity_after_warning_resets_the_silence_clock():
    # El cliente contesto "¿sigues ahí?" con un mensaje real justo despues
    # del aviso (last_activity=32, warned_at=31 -> hubo actividad DESPUES
    # del aviso) -- no debe colgar aunque hayan pasado mas de los 15s de
    # gracia desde el aviso viejo.
    action, warned_at = bridge._watchdog_decision(
        now=50.0, call_started_at=0.0, last_activity=32.0, warned_at=31.0
    )
    assert action == "none"
    assert warned_at is None  # se resetea, listo para un nuevo ciclo de silencio si vuelve a callar


def test_max_duration_wins_over_everything_else():
    # Actividad recientisima (last_activity == now) no salva de la
    # duracion maxima -- es la red de seguridad de costo definitiva.
    settings.call_max_duration_seconds = 600
    action, _ = bridge._watchdog_decision(
        now=601.0, call_started_at=0.0, last_activity=601.0, warned_at=None
    )
    assert action == "hangup_max_duration"


class FakeDeepgramWs:
    """Reemplaza al WebSocket real de Deepgram: solo graba los mensajes
    que el watchdog intenta inyectar."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


@pytest.mark.asyncio
async def test_async_loop_wiring_calls_inject_and_sets_hangup_flag():
    # Test de humo del loop async en si (no de la logica de decision, ya
    # cubierta arriba sin esperas reales): confirma que _watchdog_decision
    # esta bien conectado a la inyeccion de mensajes y al flag de colgado.
    # Umbrales bajados solo para ESTE test, con margen generoso frente al
    # poll (10x) para no depender de que el jitter de asyncio caiga justo.
    original_poll = bridge._WATCHDOG_POLL_SECONDS
    bridge._WATCHDOG_POLL_SECONDS = 0.01
    settings.call_silence_warning_seconds = 0.05
    settings.call_silence_hangup_grace_seconds = 0.05
    call_control_id = "watchdog-smoke-test"
    try:
        state = get_or_create(call_control_id, settings.default_tenant_id)
        call_started_at = time.monotonic()
        state.last_touched_at = call_started_at
        dg_ws = FakeDeepgramWs()

        task = asyncio.create_task(
            bridge._silence_and_duration_watchdog(dg_ws, call_control_id, call_started_at)
        )
        await asyncio.sleep(0.4)  # >> warning(0.05) + grace(0.05), margen amplio
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        messages = [m["message"] for m in dg_ws.sent]
        assert bridge._SILENCE_WARNING_MESSAGE in messages
        assert bridge._SILENCE_HANGUP_MESSAGE in messages
        assert state.hangup_after_response is True
    finally:
        bridge._WATCHDOG_POLL_SECONDS = original_poll
        reset(call_control_id)
