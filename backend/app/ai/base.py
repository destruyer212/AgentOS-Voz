"""Interfaz de proveedor de IA. Cualquier proveedor (rule_based, gemini,
ollama...) debe poder convertir un mensaje en una intencion estructurada.

Esto es lo que en la arquitectura del proyecto se llama "AI Router": el
runtime del agente no habla con Gemini/Ollama directamente, habla con esta
interfaz. Cambiar de proveedor es cambiar `LLM_PROVIDER` en la config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ParsedItem:
    raw_text: str
    quantity: int
    query: str
    notes: str | None = None


@dataclass
class ParsedMessage:
    intent: str
    items: list[ParsedItem] = field(default_factory=list)
    requested_time: str | None = None
    wants_human: bool = False
    confirms: bool | None = None


class LLMProvider(Protocol):
    name: str

    async def parse_message(self, message: str, *, awaiting_confirmation: bool) -> ParsedMessage: ...
