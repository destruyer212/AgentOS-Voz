"""Horario de atencion real del negocio (ver carta/horario publicado: todos
los dias de 12:00 a 23:00, hora de Peru). Vive separado de config.py porque
no es una variable de infraestructura -- es un dato de negocio que el
agente necesita para responder "¿atienden hoy?"/"¿hasta que hora?" con la
hora REAL del servidor, no adivinada ni fija en el prompt (un LLM no sabe
que hora es "ahora" sin que se lo digamos)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.infrastructure.config import settings

_DAY_NAMES_ES = (
    "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo",
)


@dataclass
class BusinessStatus:
    day_name: str
    is_open: bool
    open_time: str
    close_time: str


def _now() -> datetime:
    return datetime.now(ZoneInfo(settings.business_timezone))


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def current_business_status() -> BusinessStatus:
    now = _now()
    open_t = _parse_hhmm(settings.business_hours_open)
    close_t = _parse_hhmm(settings.business_hours_close)
    is_open = open_t <= now.time() <= close_t
    return BusinessStatus(
        day_name=_DAY_NAMES_ES[now.weekday()],
        is_open=is_open,
        open_time=settings.business_hours_open,
        close_time=settings.business_hours_close,
    )


def business_hours_message() -> str:
    """Respuesta hablada, lista para telefono/chat -- confirma si ya
    estamos atendiendo AHORA (no solo el horario general) porque eso es lo
    que de verdad quiere saber alguien que llama en este momento."""
    status = current_business_status()
    day_cap = status.day_name.capitalize()
    if status.is_open:
        return f"Sí, hoy {day_cap} estamos atendiendo, hasta las {status.close_time}."
    return (
        f"En este momento no estamos atendiendo. Hoy {day_cap} abrimos de "
        f"{status.open_time} a {status.close_time}."
    )
