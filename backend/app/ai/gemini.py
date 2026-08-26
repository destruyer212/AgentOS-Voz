"""Proveedor de IA real sobre Gemini. Implementa el mismo contrato
`LLMProvider` que `RuleBasedProvider`: el resto del sistema (agent runtime,
tools, workflow engine) no cambia nada al usar este proveedor en vez del
basado en reglas.

Le pedimos a Gemini que devuelva JSON estructurado con exactamente el mismo
esquema que produce el parser de reglas, para que ambos sean intercambiables.
Si la llamada falla (red, cuota, JSON invalido) cae automaticamente al
proveedor por reglas en vez de romper la conversacion: la IA puede fallar,
el negocio no.
"""

from __future__ import annotations

import json
import logging
import re

from google import genai
from google.genai import types

from app.ai.base import ParsedItem, ParsedMessage
from app.ai.rule_based import RuleBasedProvider
from app.infrastructure.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Eres el modulo de comprension de lenguaje (NLU) de un agente \
telefonico/chat para un restaurante. Tu unico trabajo es convertir el mensaje \
del cliente en un JSON estructurado. No converses, no expliques, no agregues \
texto fuera del JSON.

Responde EXCLUSIVAMENTE con un JSON de este esquema exacto:
{
  "intent": "order.create" | "order.modify" | "order.confirm" | "order.cancel" | "order.unclear" | "smalltalk" | "handoff",
  "items": [{"raw_text": "texto original del item", "quantity": 1, "query": "nombre del producto a buscar", "notes": "modificador o null"}],
  "requested_time": "HH:MM en formato 24h (exactamente 5 caracteres, sin segundos), o null si no menciono hora",
  "wants_human": true | false,
  "confirms": true | false | null
}

Reglas:
- "items" son productos de comida/bebida que el cliente quiere pedir. Nunca pongas ahi generalidades como "un pedido".
- "query" debe ser el nombre del producto limpio (sin cantidad, sin "sin X"), listo para buscar en un catalogo.
- MUY IMPORTANTE - modificador suelto sobre el item anterior: si una parte del mensaje es solo una
  cantidad + "sin <algo>" y NO nombra un producto nuevo (ej. "una sin cebolla", "uno sin salsa"), NO es un
  item nuevo. Es una nota que describe una unidad del item anterior. Debes fusionarla como "notes" en el
  ULTIMO item que agregaste, no crear una linea nueva. Ejemplo:
  Entrada: "dos hamburguesas dobles, una sin cebolla, tres Inca Colas"
  Salida correcta (2 items, NO 3):
  {"intent":"order.create","items":[
    {"raw_text":"dos hamburguesas dobles, una sin cebolla","quantity":2,"query":"hamburguesa doble","notes":"una sin cebolla"},
    {"raw_text":"tres Inca Colas","quantity":3,"query":"Inca Cola","notes":null}
  ],"requested_time":null,"wants_human":false,"confirms":null}
- MUY IMPORTANTE - confirmacion vs cancelacion: cuando el mensaje responde a una pregunta de
  confirmacion de pedido, cualquier negacion ("no", "no gracias", "cancela", "mejor no", "olvidalo")
  es SIEMPRE intent="order.cancel", nunca "order.confirm". Una negacion educada sigue siendo una
  negacion: "No, gracias." significa cancelar, NO confirmar. Ejemplos:
  "si" -> order.confirm | "confirmo" -> order.confirm | "dale" -> order.confirm
  "no" -> order.cancel | "no, gracias" -> order.cancel | "mejor no" -> order.cancel | "cancelalo" -> order.cancel
- "confirms" solo aplica cuando el mensaje responde una pregunta de confirmacion (si/no/dale/cancelalo). Si no aplica, usa null.
- "wants_human" es true solo si pide explicitamente hablar con una persona/asesor/humano.
- intent "smalltalk" es para saludos o mensajes sin pedido ni confirmacion ni cancelacion.
- Nunca inventes productos que el cliente no menciono.
- Hora del pedido: si el cliente dice una hora SIN especificar am/pm (ej. "a las ocho", "para las 8", "a las 3"),
  asume que es horario de almuerzo/cena: para horas de 1 a 11, interpreta como PM (ej. "a las ocho" -> "20:00",
  "a las 3" -> "15:00"). Si dice explicitamente "am" o "de la manana", usa la hora tal cual en formato 24h.
  Si dice "12" o "doce" sin am/pm, interpreta como mediodia ("12:00").
"""


class GeminiProvider:
    name = "gemini"

    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY no configurada.")
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._fallback = RuleBasedProvider()

    async def parse_message(self, message: str, *, awaiting_confirmation: bool) -> ParsedMessage:
        try:
            return await self._parse_with_gemini(message, awaiting_confirmation=awaiting_confirmation)
        except Exception:
            logger.exception("Gemini fallo interpretando el mensaje, cayendo a rule_based")
            return await self._fallback.parse_message(message, awaiting_confirmation=awaiting_confirmation)

    async def _parse_with_gemini(self, message: str, *, awaiting_confirmation: bool) -> ParsedMessage:
        context = (
            "El cliente esta respondiendo a una pregunta de confirmacion de pedido (si/no)."
            if awaiting_confirmation
            else "Es un mensaje nuevo del cliente, todavia no se le pidio confirmacion."
        )
        response = await self._client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=f"{context}\n\nMensaje del cliente: {message}",
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        data = json.loads(response.text)

        items = [
            ParsedItem(
                raw_text=item.get("raw_text", ""),
                quantity=int(item.get("quantity") or 1),
                query=item.get("query", ""),
                notes=item.get("notes"),
            )
            for item in data.get("items", [])
            if item.get("query")
        ]

        return ParsedMessage(
            intent=data.get("intent") or "order.unclear",
            items=items,
            requested_time=_normalize_time(data.get("requested_time")),
            wants_human=bool(data.get("wants_human", False)),
            confirms=data.get("confirms"),
        )


def _normalize_time(raw: str | None) -> str | None:
    """Defensa en profundidad: el prompt le pide a Gemini formato HH:MM 24h,
    pero no confiamos ciegamente en que el modelo lo respete siempre
    (modelos mas chicos a veces agregan segundos, o se escapan a 12h con
    am/pm pese a la instruccion). Normalizamos ambos casos aqui."""
    if not raw:
        return None
    match = re.match(r"^(\d{1,2}):(\d{2})\s*(am|pm)?", raw.strip(), re.IGNORECASE)
    if not match:
        return None
    hour, minute, meridiem = int(match.group(1)), match.group(2), (match.group(3) or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23):
        return None
    return f"{hour:02d}:{minute}"
