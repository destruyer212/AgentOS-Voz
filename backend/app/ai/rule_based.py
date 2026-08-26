"""Proveedor de IA basado en reglas (NLU determinista, sin costo ni llamadas
externas). Suficiente para validar el motor completo del agente en el caso
restaurante antes de conectar un LLM real (Gemini/Ollama).

Sabe:
- separar items de un pedido en lenguaje natural ("dos hamburguesas dobles,
  una sin cebolla, tres Inca Colas para las ocho")
- detectar modificadores sueltos ("sin cebolla") y asociarlos al item previo
  cuando no traen sustantivo propio
- extraer una hora solicitada ("para las ocho", "a las 8pm")
- detectar confirmacion/cancelacion cuando el agente esta esperando un "si"
- detectar pedidos de transferencia a un humano
"""

from __future__ import annotations

import re

from app.ai.base import ParsedItem, ParsedMessage
from app.domain.text_utils import normalize_text

NUMBER_WORDS = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
}
_QTY_ALTERNATION = "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))
QTY_PATTERN = rf"(\d+|{_QTY_ALTERNATION})"

CONFIRM_WORDS = {"si", "sí", "confirmo", "confirmar", "dale", "ok", "okay", "correcto", "perfecto", "asi es"}
CANCEL_WORDS = {"no", "cancela", "cancelar", "olvidalo", "olvídalo", "mejor no"}
HANDOFF_PHRASES = {"hablar con alguien", "hablar con una persona", "hablar con un humano", "asesor humano", "quiero un humano"}


def _parse_quantity(token: str | None) -> int | None:
    if not token:
        return None
    token = token.lower()
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


def _extract_time(text: str) -> tuple[str, str | None]:
    match = re.search(rf"\b(?:para|a)\s+las\s+{QTY_PATTERN}\s*(am|pm)?\b", text, re.IGNORECASE)
    if not match:
        return text, None
    hour = _parse_quantity(match.group(1)) or 0
    meridiem = (match.group(2) or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif not meridiem and 1 <= hour <= 11:
        # sin am/pm explicito asumimos horario de almuerzo/cena (1..11 -> PM)
        hour += 12
    hour %= 24
    cleaned = (text[: match.start()] + text[match.end():]).strip(" ,.")
    return cleaned, f"{hour:02d}:00"


def _split_chunks(text: str) -> list[str]:
    parts = re.split(r",|\by\b", text, flags=re.IGNORECASE)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def _extract_note(text: str) -> tuple[str, str | None]:
    match = re.search(r"\bsin\s+([a-záéíóúñ]+(?:\s+[a-záéíóúñ]+){0,2})", text, re.IGNORECASE)
    if not match:
        return text, None
    note = f"sin {match.group(1).strip()}"
    cleaned = (text[: match.start()] + text[match.end():]).strip()
    return cleaned, note


def _parse_items(text: str) -> list[ParsedItem]:
    # Descarta relleno antes del primer producto ("Hola, quiero...") para que
    # la cantidad no quede pegada a palabras como "quiero"/"hola".
    lead_match = re.search(rf"\b{QTY_PATTERN}\b", text, re.IGNORECASE)
    if lead_match:
        text = text[lead_match.start():]

    items: list[ParsedItem] = []
    for chunk in _split_chunks(text):
        qty_match = re.match(rf"^{QTY_PATTERN}\b\s*(.*)$", chunk, re.IGNORECASE)
        if qty_match:
            quantity = _parse_quantity(qty_match.group(1)) or 1
            rest = qty_match.group(2).strip()
        else:
            quantity = 1
            rest = chunk.strip()

        rest, note = _extract_note(rest)

        if not rest and note and items:
            # Modificador suelto ("una sin cebolla"): se pega al item anterior
            # en vez de crear un producto nuevo, porque no trae sustantivo.
            previous = items[-1]
            extra = f"{note} (x{quantity})" if quantity != previous.quantity else note
            previous.notes = f"{previous.notes}; {extra}" if previous.notes else extra
            continue

        if not rest:
            continue

        items.append(ParsedItem(raw_text=chunk, quantity=quantity, query=rest, notes=note))
    return items


class RuleBasedProvider:
    name = "rule_based"

    async def parse_message(self, message: str, *, awaiting_confirmation: bool) -> ParsedMessage:
        text = message.strip()
        lowered = normalize_text(text)

        if awaiting_confirmation:
            # normalize_text ya quito comas/puntos/signos ("No, gracias." -> "no gracias"),
            # asi que un split simple ya da palabras limpias para comparar.
            words = set(lowered.split())
            if words & CANCEL_WORDS or any(phrase in lowered for phrase in CANCEL_WORDS if " " in phrase):
                return ParsedMessage(intent="order.cancel", confirms=False)
            if words & CONFIRM_WORDS or any(phrase in lowered for phrase in CONFIRM_WORDS if " " in phrase):
                return ParsedMessage(intent="order.confirm", confirms=True)

            items_text, requested_time = _extract_time(text)
            items = _parse_items(items_text)
            if items:
                return ParsedMessage(intent="order.modify", items=items, requested_time=requested_time)
            return ParsedMessage(intent="order.unclear", confirms=None)

        if any(phrase in lowered for phrase in HANDOFF_PHRASES):
            return ParsedMessage(intent="handoff", wants_human=True)

        items_text, requested_time = _extract_time(text)
        items = _parse_items(items_text)
        if items:
            return ParsedMessage(intent="order.create", items=items, requested_time=requested_time)

        return ParsedMessage(intent="smalltalk")
