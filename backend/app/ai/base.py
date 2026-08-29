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
    # add: agregar al pedido (default) | remove: sacar el producto por completo
    # increase/decrease: sumar/restar `quantity` a un item que ya esta en el
    # pedido (ej. "aumenta las papas", "una hamburguesa menos").
    # set: dejar el item existente en `quantity` unidades (ej. "pon las papas a dos").
    action: str = "add"


@dataclass
class ParsedDetailAnswer:
    answers_pending_question: bool = False
    value: str | None = None


@dataclass
class ParsedMessage:
    intent: str
    items: list[ParsedItem] = field(default_factory=list)
    requested_time: str | None = None
    wants_human: bool = False
    confirms: bool | None = None
    detail_answer: ParsedDetailAnswer = field(default_factory=ParsedDetailAnswer)


class LLMProvider(Protocol):
    name: str

    async def parse_message(
        self,
        message: str,
        *,
        awaiting_confirmation: bool,
        pending_detail: str | None = None,
    ) -> ParsedMessage: ...
