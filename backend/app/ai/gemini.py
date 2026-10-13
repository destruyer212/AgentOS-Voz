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

import asyncio
import json
import logging
import re

from google import genai
from google.genai import types

from app.ai.base import ParsedDetailAnswer, ParsedItem, ParsedMessage
from app.ai.rule_based import RuleBasedProvider
from app.domain.text_utils import normalize_text
from app.infrastructure.config import settings

logger = logging.getLogger(__name__)

_FAST_PATH_SAFE_INTENTS = {"handoff", "menu.inquiry", "smalltalk"}
_FAST_PATH_ORDER_INTENTS = {"order.create", "order.modify"}
_FAST_PATH_UNSAFE_QUERY_TERMS = {
    "algo",
    "barata",
    "barato",
    "carta",
    "costo",
    "costar",
    "cuanta",
    "cuanto",
    "cuantos",
    "disponible",
    "disponibles",
    "economica",
    "economico",
    "menu",
    "opcion",
    "opciones",
    "precio",
    "precios",
    "recomienda",
    "recomiendas",
    "recomendacion",
    "saber",
    "vale",
    "valen",
}

_SYSTEM_PROMPT = """Eres el modulo de comprension de lenguaje (NLU) de un agente \
telefonico/chat para un restaurante. Tu unico trabajo es convertir el mensaje \
del cliente en un JSON estructurado. No converses, no expliques, no agregues \
texto fuera del JSON.

Responde EXCLUSIVAMENTE con un JSON de este esquema exacto:
{
  "intent": "order.create" | "order.modify" | "order.confirm" | "order.cancel" | "order.unclear" | "menu.inquiry" | "smalltalk" | "handoff",
  "items": [{"raw_text": "texto original del item", "quantity": 1, "query": "nombre del producto a buscar", "notes": "modificador o null", "action": "add"}],
  "requested_time": "HH:MM en formato 24h (exactamente 5 caracteres, sin segundos), o null si no menciono hora",
  "wants_human": true | false,
  "confirms": true | false | null,
  "detail_answer": {"answers_pending_question": true | false, "value": "respuesta limpia a la pregunta pendiente, o null"}
}

Reglas:
- "items" son productos de comida/bebida que el cliente quiere pedir. Nunca pongas ahi generalidades como "un pedido".
- "query" debe ser el nombre del producto limpio (sin cantidad, sin "sin X"), listo para buscar en un catalogo.
  Si el cliente dice el tipo generico solo ("una hamburguesa", "una bebida") sin especificar variante, deja
  "query" como ese termino generico tal cual (ej. "hamburguesa") -- el sistema se encarga de preguntar cual
  variante si hay mas de una; no inventes ni asumas tu cual variante es.
- "query" NUNCA debe incluir vocativos ni muletillas de relleno que el cliente peruano agrega sin que sean
  parte del nombre del producto (ej. "causa", "mano", "pata", "pe", "broder", "compadre"). "Quiero un pollo a
  la brasa causa" -> query "pollo a la brasa", NO "pollo a la brasa causa". Esas palabras no describen ningun
  plato real del catalogo.
- "action" (default "add") describe que hacer con ese item:
  - "add": el cliente lo quiere agregar al pedido (nuevo o repetir el mismo producto).
  - "increase": el cliente pide MAS cantidad de algo que probablemente YA esta en su pedido (ej. "aumenta las
    papas", "una hamburguesa mas", "dame otra Coca-Cola"). "quantity" es cuanto aumentar (si no da numero, usa 1).
  - "decrease": pide MENOS cantidad de algo que ya esta en el pedido (ej. "una papa menos", "quita una de las
    dos hamburguesas"). "quantity" es cuanto restar.
  - "set": pide dejar un item YA existente en una cantidad total concreta (ej. "pon las papas a dos",
    "que sean dos Coca-Colas", "aumenta las papas a dos"). "quantity" es el total final deseado, no cuanto sumar.
  - "remove": quiere sacar el producto por completo del pedido (ej. "quita las papas", "ya no quiero la bebida",
    "cancela la hamburguesa BBQ"). "quantity" no importa aqui.
- MUY IMPORTANTE - modificador suelto sobre el item anterior: si una parte del mensaje es solo una
  cantidad + "sin <algo>" y NO nombra un producto nuevo (ej. "una sin cebolla", "uno sin salsa"), NO es un
  item nuevo. Es una nota que describe una unidad del item anterior. Debes fusionarla como "notes" en el
  ULTIMO item que agregaste, no crear una linea nueva. Ejemplo:
  Entrada: "dos hamburguesas dobles, una sin cebolla, tres Inca Colas"
  Salida correcta (2 items, NO 3):
  {"intent":"order.create","items":[
    {"raw_text":"dos hamburguesas dobles, una sin cebolla","quantity":2,"query":"hamburguesa doble","notes":"una sin cebolla","action":"add"},
    {"raw_text":"tres Inca Colas","quantity":3,"query":"Inca Cola","notes":null,"action":"add"}
  ],"requested_time":null,"wants_human":false,"confirms":null}
- MUY IMPORTANTE - confirmacion vs cancelacion: cuando el mensaje responde a una pregunta de
  confirmacion de pedido, cualquier negacion ("no", "no gracias", "cancela", "mejor no", "olvidalo")
  es SIEMPRE intent="order.cancel", nunca "order.confirm". Una negacion educada sigue siendo una
  negacion: "No, gracias." significa cancelar, NO confirmar. Ejemplos:
  "si" -> order.confirm | "confirmo" -> order.confirm | "dale" -> order.confirm
  "no" -> order.cancel | "no, gracias" -> order.cancel | "mejor no" -> order.cancel | "cancelalo" -> order.cancel
- "confirms" solo aplica cuando el mensaje responde una pregunta de confirmacion (si/no/dale/cancelalo). Si no aplica, usa null.
- "detail_answer" solo aplica cuando el contexto del mensaje dice que el agente habia preguntado un dato puntual
  (name, fulfillment, address o payment). Debes marcar "answers_pending_question": true SOLO si el mensaje
  realmente responde esa pregunta. Si el cliente aprovecha para cambiar/agregar/quitar productos ("me falta una
  bebida", "ah y una Coca-Cola", "quita las papas"), entonces "answers_pending_question" debe ser false y debes
  llenar "items" con ese cambio. Si el mensaje hace ambas cosas ("delivery y agrega agua"), llena ambas partes.
  Valores esperados:
  - name: nombre limpio del cliente ("Carlos Perez"), no una frase de pedido.
  - fulfillment: "delivery" o "pickup".
  - address: direccion limpia.
  - payment: "efectivo", "yape", "plin" o "tarjeta".
- "wants_human" es true solo si pide explicitamente hablar con una persona/asesor/humano.
- intent "menu.inquiry" es cuando el cliente PREGUNTA que hay disponible, sin pedir nada todavia (ej. "¿que
  tienen?", "¿hay algo para tomar?", "¿que bebidas tienen?", "¿que me recomiendas?", "quiero ver el menu").
  En ese caso "items" va vacio -- no es un pedido, es una pregunta sobre el catalogo.
- intent "smalltalk" es para saludos o mensajes sin pedido, sin pregunta de menu, sin confirmacion ni cancelacion.
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

    async def parse_message(
        self,
        message: str,
        *,
        awaiting_confirmation: bool,
        pending_detail: str | None = None,
    ) -> ParsedMessage:
        fallback_candidate: ParsedMessage | None = None
        if settings.gemini_fast_path_enabled:
            try:
                fallback_candidate = await self._fallback.parse_message(
                    message,
                    awaiting_confirmation=awaiting_confirmation,
                    pending_detail=pending_detail,
                )
                if _is_safe_fast_path(
                    fallback_candidate,
                    message,
                    awaiting_confirmation=awaiting_confirmation,
                    pending_detail=pending_detail,
                ):
                    # Fast-path local: evita red/LLM en frases obvias
                    # ("confirmo", "delivery", "quiero una Inca Kola").
                    fallback_candidate.used_fast_path = True
                    return fallback_candidate
            except Exception:
                logger.exception("Fast-path rule_based fallo; se continua con Gemini")

        try:
            # Timeout duro y corto: visto en vivo en una llamada real, el SDK
            # de Gemini (con sus propios reintentos internos via tenacity)
            # tardo 36 SEGUNDOS en darse por vencido y recien ahi caer al
            # fallback -- en una llamada telefonica eso es silencio muerto
            # hasta que el que llama cuelga frustrado. 4s es generoso sobre
            # el baseline medido (~1.1-1.3s) pero corta mucho antes de que
            # el propio SDK termine de reintentar solo.
            return await asyncio.wait_for(
                self._parse_with_gemini(
                    message,
                    awaiting_confirmation=awaiting_confirmation,
                    pending_detail=pending_detail,
                ),
                timeout=4.0,
            )
        except Exception:
            logger.exception("Gemini fallo interpretando el mensaje, cayendo a rule_based")
            parsed = fallback_candidate
            if parsed is None:
                parsed = await self._fallback.parse_message(
                    message,
                    awaiting_confirmation=awaiting_confirmation,
                    pending_detail=pending_detail,
                )
            # Atributo dinamico (ParsedMessage no declara este campo, y no
            # hace falta: es un dataclass normal, no slots=True) -- lo lee
            # AgentRuntime para la metrica de observabilidad (VoiceTurnMetric).
            # Se pone en la instancia YA DEVUELTA de esta llamada puntual, no
            # en self/GeminiProvider (que es un singleton compartido entre
            # turnos concurrentes de conversaciones distintas -- guardar esto
            # ahi seria una condicion de carrera real, no solo teorica, dado
            # todo lo que ya se encontro hoy).
            parsed.used_fallback = True
            return parsed

    async def _parse_with_gemini(
        self,
        message: str,
        *,
        awaiting_confirmation: bool,
        pending_detail: str | None,
    ) -> ParsedMessage:
        if awaiting_confirmation:
            context = "El cliente esta respondiendo a una pregunta de confirmacion de pedido (si/no)."
        elif pending_detail:
            context = (
                "El agente acaba de pedir un dato puntual del pedido. "
                f"pending_detail={pending_detail}. Decide si el mensaje responde ese dato, "
                "si modifica el pedido, o ambas cosas."
            )
        else:
            context = "Es un mensaje nuevo del cliente, todavia no se le pidio confirmacion."
        response = await self._client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=f"{context}\n\nMensaje del cliente: {message}",
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0,
                # Probado en vivo: thinking_config/thinking_budget=0 en este
                # modelo especifico (gemini-3.5-flash-lite) devuelve 400
                # INVALID_ARGUMENT -- no lo soporta. Sin ese parametro, solo
                # acotamos el techo de tokens (nuestro JSON siempre es corto,
                # esto limita la cola de latencia sin afectar el caso normal).
                max_output_tokens=400,
            ),
        )
        data = json.loads(response.text)

        items = [
            ParsedItem(
                raw_text=item.get("raw_text", ""),
                quantity=int(item.get("quantity") or 1),
                query=item.get("query", ""),
                notes=item.get("notes"),
                action=item.get("action") or "add",
            )
            for item in data.get("items", [])
            if item.get("query")
        ]
        raw_detail = data.get("detail_answer") or {}
        detail_answer = ParsedDetailAnswer(
            answers_pending_question=bool(raw_detail.get("answers_pending_question", False)),
            value=raw_detail.get("value"),
        )

        return ParsedMessage(
            intent=data.get("intent") or "order.unclear",
            items=items,
            requested_time=_normalize_time(data.get("requested_time")),
            wants_human=bool(data.get("wants_human", False)),
            confirms=data.get("confirms"),
            detail_answer=detail_answer,
        )


def _is_safe_fast_path(
    parsed: ParsedMessage,
    message: str,
    *,
    awaiting_confirmation: bool,
    pending_detail: str | None,
) -> bool:
    if awaiting_confirmation:
        if parsed.intent in {"order.confirm", "order.cancel"}:
            return True
        return parsed.intent == "order.modify" and _items_are_safe_for_fast_path(parsed.items)

    if pending_detail:
        if parsed.detail_answer.answers_pending_question and parsed.detail_answer.value:
            return True
        if parsed.intent in {"handoff", "menu.inquiry"}:
            return True
        return parsed.intent in _FAST_PATH_ORDER_INTENTS and _items_are_safe_for_fast_path(parsed.items)

    if parsed.intent in {"handoff", "menu.inquiry"}:
        # Bug real, visto en vivo: "¿Tiene algo de menú?" clasifica sin
        # ambiguedad como menu.inquiry (correcto), pero "algo" y "menu"
        # estan en _FAST_PATH_UNSAFE_QUERY_TERMS -- una pregunta de menu
        # practicamente SIEMPRE va a contener "menu"/"carta"/"algo", asi
        # que el chequeo de terminos inseguros de abajo (pensado para
        # detectar una QUERY DE PRODUCTO vaga, ej. "algo barato") vetaba
        # el fast-path para casi cualquier pregunta real de menu. Cada vez
        # que eso pasaba, la llamada quedaba en silencio muerto hasta 4s
        # (el timeout de Gemini) antes de caer al mismo rule_based que ya
        # habia clasificado bien. Mismo criterio que ya se usaba arriba
        # cuando hay un pending_detail -- se confia en la clasificacion
        # sin filtro de terminos, siempre.
        return True
    if parsed.intent in _FAST_PATH_SAFE_INTENTS:
        return not _message_has_unsafe_terms(message)
    if parsed.intent in _FAST_PATH_ORDER_INTENTS:
        return _items_are_safe_for_fast_path(parsed.items)
    return False


def _items_are_safe_for_fast_path(items: list[ParsedItem]) -> bool:
    if not items:
        return False
    for item in items:
        query_words = set(normalize_text(item.query).split())
        raw_words = set(normalize_text(item.raw_text).split())
        if not query_words:
            return False
        if query_words & _FAST_PATH_UNSAFE_QUERY_TERMS:
            return False
        if raw_words & _FAST_PATH_UNSAFE_QUERY_TERMS:
            return False
        if item.action not in {"add", "remove", "increase", "decrease", "set"}:
            return False
        if item.quantity < 1 or item.quantity > 50:
            return False
    return True


def _message_has_unsafe_terms(message: str) -> bool:
    return bool(set(normalize_text(message).split()) & _FAST_PATH_UNSAFE_QUERY_TERMS)


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
