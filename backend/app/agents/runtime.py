"""Runtime del agente conversacional. Orquesta: intent (AI Router) ->
normalizacion de productos (tools) -> datos de entrega/pago -> confirmacion
-> workflow de fulfillment (workflow engine -> tools -> domain -> DB).

El agente nunca toca el dominio directamente; todo pasa por
`app.tools.registry.ToolRegistry`.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import ConversationState, OrderLineDraft, get_or_create
from app.ai.base import ParsedItem
from app.ai.router import ai_router
from app.ai.rule_based import CANCEL_WORDS, CONFIRM_WORDS, is_audio_repair_message, is_hours_inquiry
from app.domain.business_hours import business_hours_message
from app.domain.models import Conversation, VoiceTurnMetric, WorkflowRun
from app.domain.schemas import AgentMessageIn, AgentTurnOut, CustomerCreate, OrderOut, ToolCallOut
from app.domain.services import CustomerService, OrderService
from app.domain.text_utils import (
    normalize_spoken_fractions,
    normalize_text,
    speakify_product_name,
    tokenize,
    tokens_partial_match,
)
from app.infrastructure.config import settings
from app.integrations.wsp_notifications import fire_and_forget, notify_order_confirmed
from app.tools.registry import ToolRegistry
from app.workflows.definitions import RESTAURANT_ORDER_FULFILLMENT
from app.workflows.engine import WorkflowEngine
from app.workflows.models import WorkflowRunResult

# Sub-estados de recoleccion de datos de entrega, en el orden en que se piden.
logger = logging.getLogger(__name__)

_DETAIL_STATUSES = ("need_name", "need_fulfillment", "need_address", "need_payment")

_DETAIL_PROMPTS = {
    "name": "Para el pedido, ¿a nombre de quién lo dejo?",
    "fulfillment": "¿Lo recoges tú en el local o te lo llevamos por delivery?",
    "address": "¿Cuál es la dirección de entrega?",
    "payment": "¿Pagas en efectivo, Yape o tarjeta?",
}

# Categorias del menu y palabras que el cliente usa para referirse a ellas,
# para responder preguntas tipo "¿hay algo para tomar?" con las opciones
# reales de esa categoria en vez de un "no encontre" generico.
_MENU_CATEGORY_KEYWORDS = {
    "bebida": ["bebida", "bebidas", "tomar", "beber", "gaseosa", "gaseosas", "jugo", "refresco", "tragos"],
    "bebida_caliente": ["bebida caliente", "bebidas calientes", "infusion", "infusiones", "te", "anis", "manzanilla"],
    "entrada": ["entrada", "entradas", "piqueito", "para empezar", "choclo", "yuca", "yucas", "salchipapa"],
    "ensalada": ["ensalada", "ensaladas"],
    "pollo_brasa": ["pollo a la brasa", "brasa", "pollos", "pollo", "huayrito"],
    "oferta": ["oferta", "ofertas", "combo", "combos", "promocion", "promociones", "oferton"],
    "fusion": ["fusion", "fusiones", "mixto", "anticucho", "mollejitas"],
    "parrilla_personal": ["parrilla", "parrillas", "personal", "churrasco", "chuleta", "bife", "brocheta", "brochetas", "alitas"],
    "parrilla_familiar": ["familiar", "familiares", "para dos", "parrilla familiar"],
    "piqueo": ["piqueo", "piqueos", "chicharron"],
    "wok_criollo": ["criollo", "wok", "saltado", "tallarin", "tallarin saltado", "sopa"],
    "pasta": ["pasta", "pastas", "fetuccini", "fettuccini", "huancaina", "alfredo", "pesto"],
    "chaufa": ["chaufa", "chaufas", "aeropuerto", "mostro"],
    "complemento": ["complemento", "complementos", "guarnicion", "guarniciones", "papas", "arroz", "chorizo"],
    "menu": ["almuerzo", "lunes", "viernes", "ejecutivo"],
    "hamburguesa": ["hamburguesa", "hamburguesas"],
    "acompanamiento": ["papas", "acompañamiento", "acompanamiento", "acompañamientos", "piqueo", "entrada", "entradas"],
    "postre": ["postre", "postres", "dulce", "dulces"],
}

_MENU_CATEGORY_LABELS = {
    "bebida": "bebidas",
    "bebida_caliente": "bebidas calientes",
    "entrada": "entradas",
    "ensalada": "ensaladas",
    "pollo_brasa": "pollos a la brasa",
    "oferta": "ofertas",
    "fusion": "fusiones",
    "parrilla_personal": "parrillas personales",
    "parrilla_familiar": "parrillas familiares",
    "piqueo": "piqueos",
    "wok_criollo": "wok criollo",
    "pasta": "pastas",
    "chaufa": "chaufas",
    "complemento": "complementos",
    "menu": "menús de lunes a viernes",
    "postre": "postres",
}

_MENU_OVERVIEW_CATEGORIES = (
    "pollo_brasa",
    "oferta",
    "parrilla_personal",
    "parrilla_familiar",
    "wok_criollo",
    "pasta",
    "chaufa",
    "entrada",
    "piqueo",
    "ensalada",
    "postre",
    "bebida",
)

_MODIFIER_OPTIONS = {
    "cremas": ["ají", "mayonesa", "ketchup", "tártara", "huancaína"],
    "acompanamientos": ["papas fritas", "ensalada"],
}


def _format_money_for_voice(amount: float) -> str:
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    soles = int(value)
    cents = int((value - Decimal(soles)) * 100)

    if soles <= 0 and cents:
        cent_unit = "céntimo" if cents == 1 else "céntimos"
        return f"{cents} {cent_unit}"

    sol_unit = "sol" if soles == 1 else "soles"
    if cents == 0:
        return f"{soles} {sol_unit}"

    cent_unit = "céntimo" if cents == 1 else "céntimos"
    return f"{soles} {sol_unit} con {cents} {cent_unit}"


_NAME_PREFIX_RE = re.compile(
    r"^(mi\s+nombre\s+es|me\s+llamo|soy|es|de\s+parte\s+de|a\s+nombre\s+de)\s+",
    re.IGNORECASE,
)


def _extract_name(raw: str) -> str:
    """El cliente rara vez dice solo el nombre suelto: suele decir "me llamo
    Carlos" o "soy Carlos". Se limpia la frase para quedarnos solo con el
    nombre, sin volver a preguntar por algo que ya se dijo."""
    cleaned = raw.strip(" .")
    cleaned = _NAME_PREFIX_RE.sub("", cleaned).strip(" .")
    return cleaned or raw.strip(" .")


_ADDRESS_PREFIX_RE = re.compile(
    r"^(mi\s+direcci[oó]n\s+es|vivo\s+en|es\s+en|en)\s+",
    re.IGNORECASE,
)


def _extract_address(raw: str) -> str:
    original = raw.strip(" .")
    cleaned = _ADDRESS_PREFIX_RE.sub("", original).strip(" .")
    return cleaned or original


def _match_fulfillment(lowered: str) -> str | None:
    if any(k in lowered for k in ("delivery", "envio", "envío", "domicilio", "llevar", "llevas")):
        return "delivery"
    if any(k in lowered for k in ("recog", "recojo", "pasar", "tienda", "local", "voy yo", "paso yo")):
        return "pickup"
    return None


def _match_payment(lowered: str) -> str | None:
    # Bug real, visto en vivo: el ASR transcribio "Yape" como "yate"
    # (barco) -- fonéticamente muy parecido por telefono. Sin este alias
    # caia a la busqueda de productos ("No encontre Pago con yate en el
    # menu") en vez de reconocerse como respuesta de pago.
    if "yape" in lowered or "yate" in lowered:
        return "yape"
    # "pli" cubre el mismo tipo de corte del ASR que "yate"/"yape" arriba
    # (la palabra llega recortada por telefono). \b para no matchear "pli"
    # adentro de otra palabra (ej. "explicar", "cumplir").
    if "plin" in lowered or re.search(r"\bpli\b", lowered):
        return "plin"
    if any(k in lowered for k in ("efectivo", "cash", "contado")):
        return "efectivo"
    if "tarjeta" in lowered:
        return "tarjeta"
    return None


_DETAIL_LITERAL_BLOCKLIST = (
    "quiero", "quisiera", "dame", "deme", "falta", "agrega", "agregar", "aumenta",
    "quita", "quitar", "cambia", "cambiar", "menu", "menú", "bebida", "bebidas",
    "hamburguesa", "hamburguesas", "papas", "postre", "postres", "precio", "cuanto",
    "hola", "buenas", "gracias", "ok", "okay",
)


def _safe_literal_detail(current: str, message: str, lowered: str) -> str | None:
    """Atajo sin LLM solo para respuestas claramente literales. La regla es
    deliberadamente conservadora: ante duda, el runtime pasa por NLU y no
    guarda texto libre como nombre/direccion."""
    if any(word in lowered for word in _DETAIL_LITERAL_BLOCKLIST):
        return None

    if current == "need_name":
        cleaned = _extract_name(message)
        tokens = cleaned.split()
        # Bug real, visto en vivo: en una llamada, el nombre del cliente
        # quedo guardado literal como "¿Puede repetir?" (probablemente la
        # propia voz del agente pidiendo repetir, mal etiquetada como turno
        # del cliente por el STT) -- paso el chequeo de 1-4 palabras sin
        # digitos sin problema y termino en la confirmacion del pedido y
        # hasta en el WhatsApp real. Un nombre de verdad nunca lleva "?"/"¿".
        if 1 <= len(tokens) <= 4 and not re.search(r"\d", cleaned) and "?" not in cleaned and "¿" not in cleaned:
            return cleaned
        return None

    if current == "need_address":
        cleaned = _extract_address(message)
        address_markers = (
            "av", "avenida", "jr", "jirón", "jiron", "calle", "pasaje", "mz",
            "manzana", "lote", "departamento", "dpto", "numero", "número",
        )
        has_marker = any(marker in lowered for marker in address_markers)
        # Un numero (de casa/jiron) ya es una direccion util por si solo. Pero
        # un marcador SOLO ("Calle", sin nombre) no alcanza -- visto en vivo:
        # el que llama dice "Calle" y hace una pausa antes de dar el nombre
        # real (el STT lo entrega como dos turnos separados), y capturar
        # "Calle" ya como la direccion completa deja el pedido con una
        # direccion inutil. Con un marcador exigimos al menos una palabra
        # mas; sin marcador ni numero, mejor pasar por NLU que adivinar.
        if re.search(r"\d", cleaned):
            return cleaned
        if has_marker and len(cleaned.split()) >= 2:
            return cleaned
        return None

    return None


def _tokens_overlap(a: str, b: str) -> bool:
    """Igual/parecido tras normalizar -- match exacto, o prefijo/sufijo con
    minimo de 3 caracteres (mismo criterio que ProductService.search_scored
    -- ver tokens_partial_match -- para que "bebid" -- lo que queda de
    "bebidita" tras sacarle el diminutivo -- siga calzando contra la
    palabra clave "bebida" sin que un match a mitad de palabra genere falsos
    positivos como "cola" adentro de "chocolate")."""
    return tokens_partial_match(a, b)


def _pending_clarification_question(state: ConversationState) -> str | None:
    """Reconstruye la pregunta de desambiguacion pendiente ("¿Cuál X
    prefieres: A, B, C?") a partir de state.pending_clarification, para
    repetirla tal cual en vez de perderla con una respuesta generica.
    None si no hay ninguna pendiente o quedo sin opciones utiles."""
    pending = state.pending_clarification
    if not pending:
        return None
    query = pending.get("query") or "producto"
    options = ", ".join(
        f"{speakify_product_name(option['name'])} a {_format_money_for_voice(option['price'])}"
        if "price" in option
        else speakify_product_name(option["name"])
        for option in (pending.get("options") or [])[:4]
    )
    return f"¿Cuál {query} prefieres: {options}?" if options else None


def _resolve_pending_clarification(state: ConversationState, message: str) -> dict | None:
    """Intenta resolver una respuesta elptica a la ultima pregunta de
    desambiguacion de producto (ej. "vegetariana", "Pero te dije
    vegetariana.") contra las opciones que se ofrecieron. Solo resuelve si
    el mensaje calza con UNA sola opcion por una palabra que no sea comun a
    todas (si calzara por "hamburguesa", que esta en las 4 opciones, seria
    tan ambiguo como antes de preguntar)."""
    pending = state.pending_clarification
    if not pending:
        return None
    candidates = pending.get("options") or []
    if not candidates:
        return None
    # "un cuarto"/"medio" (como lo dice el cliente) -> "1/4"/"1/2" (como
    # esta el nombre en el catalogo) -- ver normalize_spoken_fractions.
    message_tokens = tokenize(normalize_spoken_fractions(message))
    if not message_tokens:
        return None
    all_token_sets = [set(tokenize(c["name"])) for c in candidates]
    common_tokens = set.intersection(*all_token_sets) if len(all_token_sets) > 1 else set()
    matches = []
    for candidate, candidate_tokens in zip(candidates, all_token_sets):
        distinctive = candidate_tokens - common_tokens
        if any(_tokens_overlap(mt, ct) for mt in message_tokens for ct in distinctive):
            matches.append(candidate)
    if len(matches) == 1:
        return matches[0]
    return None


def _item_answers_pending_clarification(
    pending: dict, resolved: dict, item: ParsedItem
) -> bool:
    candidates = pending.get("options") or []
    # normalize_spoken_fractions: "un cuarto de pollo" (lo que dijo el
    # cliente, y lo que queda en item.query tras sacarle un modificador
    # como "con anticucho") nunca matcheaba el "1/4" del nombre real del
    # producto resuelto -- sin esto este chequeo siempre daba False y el
    # item "sobrante" se volvia a procesar como si fuera otro pedido.
    item_tokens = set(tokenize(normalize_spoken_fractions(item.query)))
    if not candidates or not item_tokens:
        return False

    all_token_sets = [set(tokenize(candidate["name"])) for candidate in candidates]
    common_tokens = set.intersection(*all_token_sets) if len(all_token_sets) > 1 else set()
    resolved_tokens = set(tokenize(resolved["name"]))
    distinctive_tokens = resolved_tokens - common_tokens
    return bool(item_tokens & distinctive_tokens) or item_tokens <= resolved_tokens


def _detect_menu_category(message: str) -> str | None:
    # tokenize() (no substring crudo sobre el texto completo): normaliza
    # plurales Y diminutivos ("hamburguesita"/"bebidita"). Con el substring
    # crudo de antes, esas formas no calzaban contra la palabra clave
    # ("hamburguesa"/"bebida") y la pregunta se respondia con el menu
    # completo en vez de solo la categoria pedida -- bug real, visto en vivo.
    message_tokens = tokenize(message)
    for category, keywords in _MENU_CATEGORY_KEYWORDS.items():
        keyword_tokens = {token for kw in keywords for token in tokenize(kw)}
        if any(_tokens_overlap(mt, kt) for mt in message_tokens for kt in keyword_tokens):
            return category
    return None


def _detect_modifier_inquiry(message: str) -> str | None:
    message_tokens = tokenize(message)
    if any(_tokens_overlap(mt, kt) for mt in message_tokens for kt in ("crema", "salsa", "aji")):
        return "cremas"
    if any(_tokens_overlap(mt, kt) for mt in message_tokens for kt in ("ensalada", "acompanamiento", "guarnicion")):
        return "acompanamientos"
    return None


def _safety_override_intent(message: str, awaiting_confirmation: bool, intent: str) -> str:
    """Red de seguridad determinista, independiente de que proveedor de IA
    este activo: la decision de "el cliente confirmo un pedido real" (->
    stock descontado, dinero comprometido) nunca queda solo en manos de la
    interpretacion de un LLM. Si el proveedor dice "order.confirm" pero el
    mensaje trae una palabra de negacion inequivoca ("no", "cancela"...),
    gana la lectura literal: mejor pedir que confirme de nuevo que crear
    un pedido que el cliente acaba de rechazar. Visto en vivo: un modelo
    barato leyo "No, gracias." como confirmacion.
    """
    if not awaiting_confirmation or intent != "order.confirm":
        return intent
    words = set(normalize_text(message).split())
    if words & CANCEL_WORDS:
        return "order.cancel"
    return intent


def _transcript_line(role: str, text: str) -> str:
    """El transcript persistido se parsea despues linea por linea ("cliente:
    ..." / "agente: ..."), asi que un salto de linea suelto dentro del texto
    (una respuesta larga de Gemini con formato, por ejemplo) rompería esa
    invariante y el turno se veria cortado en pedazos falsos en el frontend."""
    return f"{role}: {text.replace(chr(10), ' ').strip()}"


def _reset_order_draft(state: ConversationState) -> None:
    state.items.clear()
    state.unresolved.clear()
    state.requested_time = None
    state.fulfillment_type = None
    state.delivery_address = None
    state.payment_method = None
    state.silence_retries = 0
    state.pending_clarification = None
    state.hangup_after_response = False


class AgentRuntime:
    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id
        self.tools = ToolRegistry(session, tenant_id)

    async def handle_turn(self, payload: AgentMessageIn) -> AgentTurnOut:
        state = get_or_create(payload.conversation_id, self.tenant_id)
        # Observabilidad (VoiceTurnMetric): arranca el cronometro de ESTE
        # turno. Se resetea used_fallback_this_turn aca tambien -- si no,
        # un fallback de un turno anterior quedaria marcado en el turno
        # actual aunque este no haya necesitado caer a rule_based.
        state.turn_started_at = time.monotonic()
        state.used_fallback_this_turn = False
        if state.status == "closed":
            _reset_order_draft(state)
            state.status = "collecting"
        state.channel = payload.channel
        state.transcript.append(_transcript_line("cliente", payload.message))

        if payload.customer_phone or payload.customer_name:
            await self._resolve_customer(state, payload)

        tool_calls: list[ToolCallOut] = []

        # "¿Atienden hoy?"/"¿hasta que hora abren?" -- se chequea ANTES que
        # todo lo demas (incluso antes de la recoleccion de datos) porque es
        # una pregunta valida en cualquier momento de la llamada, y la
        # respuesta depende de la hora REAL del servidor, no de NLU. Si
        # habia una pregunta pendiente (nombre/entrega/direccion/pago), se
        # repite despues de contestar para no perder el hilo del pedido.
        if is_hours_inquiry(payload.message):
            response = business_hours_message()
            if state.status in _DETAIL_STATUSES:
                response += f" {_DETAIL_PROMPTS[state.status[len('need_'):]]}"
            return await self._finish(state, response, "hours.inquiry", [], tool_calls, None)

        # Sub-estados de recoleccion de datos (nombre/entrega/pago): no pasan
        # por el NLU de pedidos, se interpretan directo como respuesta a la
        # pregunta puntual que se hizo en el turno anterior.
        if state.status in _DETAIL_STATUSES:
            return await self._handle_detail_answer(state, payload.message, tool_calls)

        provider = ai_router.get_provider()
        awaiting_confirmation = state.status == "awaiting_confirmation"
        parsed = await provider.parse_message(payload.message, awaiting_confirmation=awaiting_confirmation)
        state.used_fallback_this_turn = getattr(parsed, "used_fallback", False)
        parsed.intent = _safety_override_intent(payload.message, awaiting_confirmation, parsed.intent)

        # Bug real, visto en vivo: tras preguntar "Cual gaseosa prefieres:
        # ...?", el cliente contesto un fragmento cortado por el STT ("Una
        # de") que el parser no reconocio como pedido -- caia en intent
        # "smalltalk" (no "order.create"/"order.modify"), asi que el
        # intento de resolver la aclaracion pendiente de mas abajo NUNCA se
        # ejecutaba (solo corria para esos dos intents especificos). El
        # agente respondia un generico "Dime que te provoca pedir hoy?",
        # perdiendo la pregunta pendiente y el pedido que el cliente venia
        # armando. Se intenta resolver ANTES de mirar el intent: si
        # calza, se fuerza a order.modify y sigue el flujo normal.
        if state.pending_clarification and not parsed.items and parsed.intent not in ("order.create", "order.modify"):
            resolved = _resolve_pending_clarification(state, payload.message)
            if resolved:
                parsed.items = [
                    ParsedItem(raw_text=payload.message, quantity=1, query=resolved["name"], action="add")
                ]
                parsed.intent = "order.modify"

        # Bug real, visto en vivo: el resumen final mostro un nombre mal
        # capturado ("A nombre de ¿Puede repetir?. ¿Confirmas?") y el
        # cliente intento corregirlo tres veces ("Dayana.", "Mi nombre es",
        # "Mi nombre es Dayana.") -- cada intento se buscaba como PRODUCTO
        # ("No encontre Dayana en el menu") en vez de reconocerse como una
        # correccion de nombre, y el resumen seguia mostrando el nombre
        # viejo. Solo se activa con un prefijo explicito ("mi nombre es"/
        # "me llamo"/etc, ver _NAME_PREFIX_RE) para no confundir una
        # correccion de nombre con una modificacion real del pedido.
        if awaiting_confirmation and state.items and _NAME_PREFIX_RE.match(payload.message.strip()):
            corrected_name = _extract_name(payload.message)
            if corrected_name and not re.search(r"[\d?¿]", corrected_name):
                state.customer = {**(state.customer or {}), "name": corrected_name}
                if state.customer.get("id"):
                    await CustomerService(self.session, self.tenant_id).update_name(
                        state.customer["id"], corrected_name
                    )
                state.has_real_name = True
                response = "Listo, corregido. " + self._build_summary(state)
                return await self._finish(state, response, "order.modify", [], tool_calls, None)

        if parsed.intent == "handoff":
            await self._call_tool(
                tool_calls, "conversation.transfer_to_human",
                {"conversation_id": state.id, "reason": payload.message},
            )
            state.status = "closed"
            return await self._finish(
                state, "Claro, te paso con alguien del equipo. Un momento.", "handoff", [], tool_calls, None
            )

        if parsed.intent == "menu.inquiry":
            return await self._handle_menu_inquiry(state, payload.message, tool_calls)

        if parsed.intent == "smalltalk":
            # El saludo completo ("Hola, buenas...") solo tiene sentido en el
            # primer turno de la conversacion. Bug real, visto en vivo: una
            # frase mal entendida a mitad de un pedido (ej. "Una vez estaria
            # bien.", una transcripcion garbled) caia en "smalltalk" y
            # respondia el saludo de bienvenida de nuevo -- el pedido seguia
            # intacto (state.items no se toca aca), pero sonaba como si el
            # agente hubiera olvidado todo y reiniciado la llamada. Con algo
            # de progreso ya hecho, es mejor pedir que repita.
            #
            # En telefono el saludo YA lo dijo Deepgram directamente (campo
            # "greeting" del Settings, ver voice_agent_bridge.py) sin pasar
            # nunca por este runtime -- para nosotros, el primer turno real
            # de una llamada es el primer mensaje que SI llega aca, y suele
            # ser un "¿Aló?" que cae en smalltalk. Repetir el saludo completo
            # ahi sonaba, en vivo, como si el saludo se hubiera cortado y el
            # agente hubiera vuelto a saludar desde cero. Por eso en telefono
            # nunca repetimos el saludo completo, solo en canales donde
            # nosotros somos quienes saludan primero (web/whatsapp).
            if state.channel == "phone":
                if is_audio_repair_message(payload.message):
                    if state.status == "awaiting_confirmation" and state.items:
                        response = "Te escucho. Te repito: " + self._build_summary(state)
                    else:
                        clarification = _pending_clarification_question(state)
                        response = (
                            f"Te escucho. {clarification}" if clarification
                            else "Te escucho. Repíteme tu pedido, por favor."
                        )
                else:
                    # Bug real, visto en vivo: tras "Cual gaseosa prefieres:
                    # ...?", un fragmento cortado ("Una de") que ni siquiera
                    # el intento de resolucion de arriba pudo calzar caia
                    # aca y perdia la pregunta pendiente por completo con un
                    # generico "Dime que te provoca pedir hoy?". Si sigue
                    # habiendo una aclaracion pendiente, se repite ESA
                    # pregunta en vez de sonar como que se olvido todo.
                    clarification = _pending_clarification_question(state)
                    response = clarification or "Dime, ¿qué te provoca pedir hoy?"
            else:
                response = (
                    f"Hola, buenas, bienvenido a {settings.restaurant_name}. ¿Qué te provoca pedir hoy?"
                    if not state.items and not state.transcript[:-1]
                    else "Perdón, no te entendí bien. ¿Me lo repites?"
                )
            return await self._finish(state, response, "smalltalk", [], tool_calls, None)

        if parsed.intent in ("order.create", "order.modify"):
            # Bug real, visto en vivo: tras preguntar "Cual hamburguesa
            # prefieres: BBQ, Clasica, Doble, Vegetariana?", el cliente
            # respondio "Pero te dije vegetariana." -- el parser (rule_based
            # o Gemini) no reconoce eso como un pedido (no tiene "quiero"/
            # "una X", es una queja), asi que parsed.items salia vacio y el
            # agente contestaba "No te entendi bien" IGNORANDO que habia una
            # pregunta de desambiguacion pendiente -- perdia el progreso del
            # pedido y sonaba como si no hubiera escuchado nada. Si el
            # parser no saco ningun item pero hay una desambiguacion
            # pendiente, intentamos resolverla nosotros contra el mensaje
            # crudo antes de rendirnos.
            if state.pending_clarification:
                resolved = _resolve_pending_clarification(state, payload.message)
                if resolved:
                    parsed.items = [
                        ParsedItem(raw_text=payload.message, quantity=1, query=resolved["name"], action="add"),
                        *[
                            item
                            for item in parsed.items
                            if not _item_answers_pending_clarification(
                                state.pending_clarification,
                                resolved,
                                item,
                            )
                        ],
                    ]

            missing, clarifications = await self._normalize_items(state, parsed.items, tool_calls)
            if parsed.requested_time:
                state.requested_time = parsed.requested_time

            if clarifications:
                state.status = "collecting"
                return await self._finish(state, " ".join(clarifications), "order.clarify", missing, tool_calls, None)

            if missing:
                state.status = "collecting"
                response = "No encontré " + "; ".join(missing) + " en el menú. ¿Me lo repites o pides otra cosa?"
                return await self._finish(state, response, "order.create", missing, tool_calls, None)

            if not state.items:
                return await self._finish(
                    state, "No te entendí bien. ¿Qué te gustaría pedir?",
                    "order.create", [], tool_calls, None,
                )

            return await self._advance_order(state, tool_calls)

        if parsed.intent == "order.confirm" and state.status == "awaiting_confirmation":
            order = await self._confirm_order(state, tool_calls)
            if order is None:
                state.status = "collecting"
                reason = state.unresolved[-1] if state.unresolved else "intenta de nuevo."
                response = f"Uy, hubo un problema: {reason}"
                return await self._finish(state, response, "order.confirm", [], tool_calls, None)

            state.status = "closed"
            # Señal explicita para telefonia (ver voice_agent_bridge.py):
            # colgar solo automaticamente cuando el pedido se confirmo de
            # verdad. status=="closed" tambien se usa para handoff -- colgar
            # ahi seria mucho peor que no colgar (cortarle la llamada a
            # alguien que pidio hablar con una persona).
            state.hangup_after_response = True
            # Dispara el WhatsApp real en paralelo, sin esperarlo: si
            # wsp-service esta lento, caido, o sin configurar, la llamada
            # igual sigue y cuelga normal -- ver wsp_notifications.py.
            customer_phone = state.customer.get("phone") if state.customer else None
            fire_and_forget(notify_order_confirmed(order, customer_phone))
            time_part = f" para las {order.requested_time}" if order.requested_time else ""
            response = (
                f"Listo, pedido confirmado{time_part}, son {_format_money_for_voice(order.total)}. "
                "Te llega la confirmación por mensaje. ¡Gracias!"
            )
            return await self._finish(state, response, "order.confirm", [], tool_calls, order)

        if parsed.intent == "order.cancel":
            _reset_order_draft(state)
            state.status = "collecting"
            return await self._finish(
                state, "Listo, cancelado. ¿Deseas pedir algo más?",
                "order.cancel", [], tool_calls, None,
            )

        return await self._finish(
            state, "¿Confirmas el pedido, sí o no?",
            parsed.intent, [], tool_calls, None,
        )

    async def _resolve_customer(self, state: ConversationState, payload: AgentMessageIn) -> None:
        if state.customer or not (payload.customer_phone or payload.customer_name):
            return
        data = CustomerCreate(name=payload.customer_name or "Cliente telefonico", phone=payload.customer_phone)
        customer = await CustomerService(self.session, self.tenant_id).get_or_create(data)
        await self.session.commit()
        state.customer = {"id": customer.id, "name": customer.name, "phone": customer.phone, "address": customer.address}
        # Si el cliente dio su nombre explicitamente, o si ya existia en la
        # ficha con un nombre real (cliente recurrente por telefono), no hace
        # falta volver a preguntarlo durante la llamada.
        if payload.customer_name or (customer.name and customer.name != "Cliente telefonico"):
            state.has_real_name = True

    async def _call_tool(self, tool_calls: list[ToolCallOut], name: str, arguments: dict) -> dict:
        result = await self.tools.call(name, arguments)
        tool_calls.append(ToolCallOut(name=name, arguments=arguments, result=result))
        return result

    async def _handle_menu_inquiry(
        self, state: ConversationState, message: str, tool_calls: list[ToolCallOut]
    ) -> AgentTurnOut:
        modifier_kind = _detect_modifier_inquiry(message)
        if modifier_kind:
            options = ", ".join(_MODIFIER_OPTIONS[modifier_kind])
            response = f"Tenemos {modifier_kind}: {options}. ¿Cuál te agrego?"
            return await self._finish(state, response, "menu.inquiry", [], tool_calls, None)

        category = _detect_menu_category(message)
        result = await self._call_tool(tool_calls, "products.menu", {"category": category})
        products = result.get("products", [])
        if not products:
            response = "Por ahora no tengo nada en esa categoría. ¿Quieres que te cuente el menú completo?"
        elif not category:
            available_categories = {p["category"] for p in products}
            category_names = [
                _MENU_CATEGORY_LABELS[cat]
                for cat in _MENU_OVERVIEW_CATEGORIES
                if cat in available_categories
            ]
            readable_categories = (
                category_names[0]
                if len(category_names) == 1
                else ", ".join(category_names[:-1]) + f" y {category_names[-1]}"
            )
            response = (
                f"Tenemos {readable_categories}. ¿Qué categoría te provoca?"
            )
        else:
            names = [
                f"{speakify_product_name(p['name'])} a {_format_money_for_voice(p['price'])}" for p in products[:6]
            ]
            intro = f"En {_MENU_CATEGORY_LABELS.get(category, 'esa categoría')} tenemos: "
            response = intro + ", ".join(names) + ". ¿Qué te provoca?"
        return await self._finish(state, response, "menu.inquiry", [], tool_calls, None)

    def _find_existing_item(self, state: ConversationState, query: str) -> OrderLineDraft | None:
        """Busca en lo que el cliente ya lleva pedido un item que calce con
        `query` (por token, igual que el matching de catalogo), para poder
        resolver "aumenta las papas" / "quita la hamburguesa" contra la
        linea correcta en vez de contra el catalogo entero."""
        query_tokens = set(tokenize(query))
        if not query_tokens:
            return None
        best, best_overlap = None, 0
        for line in state.items:
            overlap = len(query_tokens & set(tokenize(line.name)))
            if overlap > best_overlap:
                best, best_overlap = line, overlap
        return best

    async def _normalize_items(
        self, state: ConversationState, parsed_items: list[ParsedItem], tool_calls: list[ToolCallOut]
    ) -> tuple[list[str], list[str]]:
        missing: list[str] = []
        clarifications: list[str] = []
        # Terminos que quedaron ambiguos EN ESTE MISMO TURNO (ej. "hamburguesa"
        # -> se pregunto cual variante). Si un item posterior del mismo mensaje
        # resuelve a un producto cuyo nombre contiene ese termino (ej. "BBQ" ->
        # "Hamburguesa BBQ"), lo mas probable es que sea la aclaracion de la
        # misma frase dicha con una pausa ("una hamburguesa, BBQ"), no un
        # pedido nuevo. Sin este chequeo se agregaba la BBQ ya resuelta Y
        # ademas se preguntaba cual hamburguesa -- si el cliente contestaba
        # "BBQ" a esa pregunta, terminaba con dos hamburguesas BBQ cobradas.
        ambiguous_query_tokens: list[set[str]] = []
        # Foto de como estaba ANTES de este turno -- el chequeo de mas
        # abajo solo debe resolver contra una aclaracion que ya estaba
        # pendiente de un turno anterior, nunca contra una que se genera
        # recien en este mismo mensaje (eso es el caso "una hamburguesa,
        # BBQ" de arriba, que ambiguous_query_tokens ya cubre distinto: ahi
        # NO hay que resolver de una, hay que esperar la respuesta).
        pending_clarification_before_turn = state.pending_clarification
        # Tokens del producto YA resuelto en este mismo turno via la
        # aclaracion pendiente (ver mas abajo). Bug real, visto en vivo: el
        # parser separa "un cuarto de pollo con anticucho, el olivar." en
        # DOS items -- el primero resuelve bien contra la aclaracion
        # pendiente ("...con anticucho" -> "1/4 Pollo... Anticucho"), pero
        # el segundo ("el olivar", el resto de la MISMA frase) se buscaba
        # de cero como si fuera OTRO producto, encontraba varios "El
        # Olivar" sueltos (ensalada, menu, etc.) y pisaba la aclaracion ya
        # resuelta con una pregunta nueva -- el cliente sentia que nunca
        # se le entendia nada.
        resolved_via_pending_tokens: list[set[str]] = []

        for item in parsed_items:
            action = item.action or "add"

            if action in ("remove", "increase", "decrease", "set"):
                existing = self._find_existing_item(state, item.query)
                if not existing:
                    if action == "remove":
                        continue  # nada que quitar todavia, no es un error grave
                    missing.append(item.raw_text)
                    continue
                if action == "remove":
                    state.items.remove(existing)
                elif action == "increase":
                    existing.quantity += max(item.quantity, 1)
                elif action == "decrease":
                    existing.quantity -= max(item.quantity, 1)
                    if existing.quantity <= 0:
                        state.items.remove(existing)
                elif action == "set":
                    existing.quantity = max(item.quantity, 1)
                continue

            # Bug real, visto en vivo: con una desambiguacion pendiente (ej.
            # "¿Cual pollo a la brasa prefieres: medio, un cuarto, ...?"),
            # la respuesta del cliente ("un cuarto de pollo a la brasa del
            # menu") suele parsear como un pedido nuevo (order.create), no
            # como una respuesta -- eso saltaba por completo la logica de
            # desambiguacion y volvia a buscar el producto desde cero. Como
            # "un cuarto de pollo a la brasa" no matchea NINGUN producto por
            # nombre exacto, caia otra vez en el listado completo de la
            # categoria y repetia la MISMA pregunta con las 4 opciones, sin
            # avanzar nunca. Se intenta resolver contra lo pendiente ANTES
            # de una busqueda nueva -- si el cliente ya dijo algo que
            # distingue una opcion (ej. "del menu"), se usa esa.
            if (
                pending_clarification_before_turn is not None
                and state.pending_clarification is pending_clarification_before_turn
            ):
                resolved = _resolve_pending_clarification(state, item.raw_text)
                if resolved:
                    state.pending_clarification = None
                    self._add_or_increment_item(state, resolved, item.quantity, item.notes)
                    resolved_via_pending_tokens.append(set(tokenize(resolved["name"])))
                    continue

            # Resto de la MISMA frase que ya resolvio la aclaracion pendiente
            # arriba (ej. "el olivar" despues de "...con anticucho") -- no es
            # un producto nuevo, es la cola de lo que ya se agrego.
            # normalize_spoken_fractions por el mismo motivo que arriba.
            item_query_tokens = set(tokenize(normalize_spoken_fractions(item.query)))
            if item_query_tokens and any(
                item_query_tokens <= resolved_tokens for resolved_tokens in resolved_via_pending_tokens
            ):
                continue

            result = await self._call_tool(tool_calls, "products.search", {"query": item.query})
            candidates = result.get("products", [])
            if not candidates:
                category = _detect_menu_category(item.query)
                if category:
                    menu_result = await self._call_tool(tool_calls, "products.menu", {"category": category})
                    options = menu_result.get("products", [])
                    if options and clarifications:
                        # Bug real, visto en vivo: "un cuarto de pollo, el
                        # olivar" -- dos fragmentos AMBIGUOS en el mismo
                        # mensaje generaban DOS preguntas de aclaracion
                        # pegadas en una sola respuesta ("Cual cuarto de
                        # pollo prefieres...? Cual olivar prefieres...?"),
                        # y la segunda pisaba el pending_clarification de
                        # la primera -- resultado: loop sin poder avanzar
                        # nunca. Solo se pregunta UNA cosa por turno; el
                        # segundo fragmento ambiguo se guarda como
                        # "missing" y el cliente lo puede repetir despues
                        # de resolver la primera.
                        missing.append(item.raw_text)
                        continue
                    if options:
                        # Bug real, visto en vivo: "Quiero ofertas" -> la
                        # respuesta vieja era "Que ofertas prefieres: Mega
                        # Oferton, Oferton, Pollo a la Brasa para Dos, Super
                        # Oferton?" -- 4 nombres seguidos sin precio ni pausa,
                        # dichos por voz suenan como un solo bloque y el
                        # cliente entendia que solo se habia mencionado una.
                        # Mismo formato "nombre a tanto soles" que ya usa el
                        # menu.inquiry (linea ~607), mucho mas facil de
                        # seguir por telefono.
                        label = _MENU_CATEGORY_LABELS.get(category, item.query)
                        option_names = ", ".join(
                            f"{speakify_product_name(option['name'])} a {_format_money_for_voice(option['price'])}"
                            for option in options[:5]
                        )
                        clarifications.append(f"En {label} tenemos: {option_names}. ¿Cuál prefieres?")
                        state.pending_clarification = {"query": item.query, "options": options[:5]}
                        continue
                missing.append(item.raw_text)
                continue

            if result.get("ambiguous") and clarifications:
                # Mismo motivo que arriba: no apilar una segunda pregunta
                # de aclaracion en el mismo turno.
                missing.append(item.raw_text)
                continue

            if result.get("ambiguous"):
                # Termino generico ("hamburguesa") que calza igual con varias
                # variantes: preguntamos en vez de adivinar cual. Con precio
                # por la misma razon que arriba: mas facil de distinguir por
                # telefono que una lista de nombres seguidos.
                options = ", ".join(
                    f"{speakify_product_name(c['name'])} a {_format_money_for_voice(c['price'])}"
                    for c in candidates[:4]
                )
                clarifications.append(f"¿Cuál {item.query} prefieres: {options}?")
                ambiguous_query_tokens.append(set(tokenize(item.query)))
                state.pending_clarification = {"query": item.query, "options": candidates[:4]}
                continue

            best = candidates[0]
            best_tokens = set(tokenize(best["name"]))
            if any(qt and qt <= best_tokens for qt in ambiguous_query_tokens):
                continue  # es la aclaracion de una ambiguedad de este mismo turno, no un item nuevo

            # Un item resuelto solo debe cerrar la desambiguacion pendiente si
            # realmente responde esa pregunta. En voz, el STT puede juntar
            # "hamburguesa chicha morada" sin coma: se pregunta cual
            # hamburguesa, pero la chicha se resuelve en el mismo turno. Si
            # borraramos pending_clarification por cualquier producto resuelto,
            # perderiamos la pregunta de la hamburguesa.
            if state.pending_clarification:
                pending_tokens = set(tokenize(str(state.pending_clarification.get("query", ""))))
                if pending_tokens and pending_tokens & best_tokens:
                    state.pending_clarification = None

            self._add_or_increment_item(state, best, item.quantity, item.notes)
        return missing, clarifications

    @staticmethod
    def _add_or_increment_item(state: ConversationState, product: dict, quantity: int, notes: str | None) -> None:
        """Suma cantidad si el producto ya esta en el carrito, o lo agrega
        de nuevo -- logica compartida entre la resolucion de una
        aclaracion pendiente y el match directo por busqueda."""
        existing = next((line for line in state.items if line.product_id == product["id"]), None)
        if existing:
            existing.quantity += quantity
            if notes:
                existing.notes = f"{existing.notes}; {notes}" if existing.notes else notes
        else:
            state.items.append(
                OrderLineDraft(
                    product_id=product["id"], name=product["name"], quantity=quantity,
                    unit_price=product["price"], notes=notes,
                )
            )

    def _next_missing_detail(self, state: ConversationState) -> str | None:
        if not state.has_real_name:
            return "name"
        if not state.fulfillment_type:
            return "fulfillment"
        if state.fulfillment_type == "delivery" and not state.delivery_address:
            return "address"
        if not state.payment_method:
            return "payment"
        return None

    async def _advance_order(self, state: ConversationState, tool_calls: list[ToolCallOut]) -> AgentTurnOut:
        """Una vez que los items del pedido estan completos, pide los datos
        que falten (nombre, delivery/recojo, direccion, forma de pago) antes
        de pasar al resumen final. Un dato a la vez, en orden fijo."""
        missing_detail = self._next_missing_detail(state)
        if missing_detail:
            state.status = f"need_{missing_detail}"
            return await self._finish(state, _DETAIL_PROMPTS[missing_detail], "order.create", [], tool_calls, None)
        state.status = "awaiting_confirmation"
        return await self._finish(state, self._build_summary(state), "order.create", [], tool_calls, None)

    async def _handle_detail_answer(
        self, state: ConversationState, message: str, tool_calls: list[ToolCallOut]
    ) -> AgentTurnOut:
        current = state.status
        lowered = normalize_text(message)
        words = set(lowered.split())
        pending_key = current[len("need_"):]
        pending_prompt = _DETAIL_PROMPTS[pending_key]

        if is_audio_repair_message(message):
            return await self._finish(state, f"Te escucho. {pending_prompt}", "smalltalk", [], tool_calls, None)

        # Cancelar sigue disponible en cualquier momento, incluso a mitad de
        # esta recoleccion de datos.
        if words & CANCEL_WORDS:
            _reset_order_draft(state)
            state.status = "collecting"
            return await self._finish(
                state, "Listo, cancelado. ¿Deseas pedir algo más?", "order.cancel", [], tool_calls, None
            )

        # Bug real, visto en vivo: "Perfecto." solo (una afirmacion generica,
        # sin contenido) durante la recoleccion de datos no calza ni como
        # fulfillment ni como pago -- caia al parser de items y se buscaba
        # como si fuera un producto ("No encontré Perfecto en el menú").
        # Ninguna de estas preguntas (nombre/entrega/direccion/pago) tiene
        # una respuesta valida hecha solo de afirmaciones ("si", "dale",
        # "ok", "perfecto"...), asi que si el mensaje es SOLO eso, mejor
        # repetir la pregunta que inventar una busqueda sin sentido.
        if words and words <= CONFIRM_WORDS:
            return await self._finish(
                state, f"Perdón, no te entendí bien. {pending_prompt}", "detail.unclear", [], tool_calls, None
            )

        # Ruta ultrarrapida y segura: fulfillment/pago son vocabularios
        # cerrados. Si calzan directo, no llamamos a Gemini.
        if current == "need_fulfillment":
            match = _match_fulfillment(lowered)
            if match:
                await self._apply_detail_answer(state, current, match)
                return await self._advance_order(state, tool_calls)
        elif current == "need_payment":
            match = _match_payment(lowered)
            if match:
                await self._apply_detail_answer(state, current, match)
                return await self._advance_order(state, tool_calls)

        # Ruta barata y conservadora para texto libre obvio ("Carlos",
        # "Av. Siempre Viva 123"). Si hay señales de pedido/menu/comando, no
        # captura nada: pasa por NLU para no tragarse intenciones.
        literal = _safe_literal_detail(current, message, lowered)
        if literal:
            await self._apply_detail_answer(state, current, literal)
            return await self._advance_order(state, tool_calls)

        provider = ai_router.get_provider()
        parsed = await provider.parse_message(
            message,
            awaiting_confirmation=False,
            pending_detail=pending_key,
        )
        state.used_fallback_this_turn = getattr(parsed, "used_fallback", False)

        if parsed.intent == "handoff":
            await self._call_tool(
                tool_calls,
                "conversation.transfer_to_human",
                {"conversation_id": state.id, "reason": message},
            )
            state.status = "closed"
            return await self._finish(
                state, "Claro, te paso con alguien del equipo. Un momento.", "handoff", [], tool_calls, None
            )

        if parsed.intent == "menu.inquiry":
            return await self._handle_menu_inquiry(state, message, tool_calls)

        if parsed.requested_time:
            state.requested_time = parsed.requested_time

        if parsed.items or parsed.intent in ("order.create", "order.modify"):
            missing, clarifications = await self._normalize_items(state, parsed.items, tool_calls)

            if not state.items:
                state.status = "collecting"
                response = "Tu pedido quedó vacío. ¿Qué te gustaría pedir?"
                if missing:
                    response = "No encontré " + "; ".join(missing) + " en el menú. ¿Qué te gustaría pedir?"
                return await self._finish(state, response, "order.create", missing, tool_calls, None)

            if clarifications:
                state.status = "collecting"
                return await self._finish(state, " ".join(clarifications), "order.clarify", missing, tool_calls, None)

            if parsed.detail_answer.answers_pending_question and parsed.detail_answer.value:
                await self._apply_detail_answer(state, current, parsed.detail_answer.value)
                return await self._advance_order(state, tool_calls)

            if missing:
                edit_ack = "No encontré " + "; ".join(missing) + " en el menú. "
            elif parsed.items:
                # Solo confirmamos "actualice el pedido" si de verdad se
                # proceso algun item. Visto en vivo: un fragmento cortado por
                # el STT ("Tambien quiero agregar", sin nombrar el producto
                # todavia) clasificaba como order.modify sin items concretos
                # -- decir "listo, actualice" ahi era falso y confundio al
                # que llamaba (termino pidiendo un humano sin necesidad).
                edit_ack = "Listo, actualicé el pedido. "
            else:
                edit_ack = ""
            return await self._finish(state, edit_ack + pending_prompt, "order.modify", missing, tool_calls, None)

        if parsed.detail_answer.answers_pending_question and parsed.detail_answer.value:
            await self._apply_detail_answer(state, current, parsed.detail_answer.value)
            return await self._advance_order(state, tool_calls)

        # Ultima defensa: si no se entendio si respondia la pregunta o si
        # queria modificar el pedido, no guardamos texto libre. Repreguntamos
        # explicitamente para evitar corrupcion silenciosa de nombre/direccion.
        return await self._finish(
            state,
            f"No quiero perder lo que dijiste. {pending_prompt}",
            "detail.unclear",
            [],
            tool_calls,
            None,
        )

    async def _apply_detail_answer(self, state: ConversationState, current: str, raw_value: str) -> None:
        if current == "need_name":
            name = _extract_name(raw_value)
            state.customer = {**(state.customer or {}), "name": name}
            state.has_real_name = True
            if state.customer.get("id"):
                await CustomerService(self.session, self.tenant_id).update_name(state.customer["id"], name)
                await self.session.commit()
            return

        if current == "need_fulfillment":
            value = _match_fulfillment(normalize_text(raw_value)) or normalize_text(raw_value)
            if value not in {"delivery", "pickup"}:
                return
            state.fulfillment_type = value
            if state.fulfillment_type == "delivery" and state.customer and state.customer.get("address"):
                state.delivery_address = state.customer["address"]
            return

        if current == "need_address":
            address = _extract_address(raw_value)
            state.delivery_address = address
            if state.customer:
                # Tambien en el snapshot en memoria, no solo en state.delivery_address:
                # si el mismo llamante pide de nuevo mas adelante en la misma
                # llamada (ver _reset_order_draft), el auto-relleno de
                # direccion en _apply_detail_answer("need_fulfillment") lee
                # state.customer["address"] -- sin esto, usaria la direccion
                # vieja que tenia la ficha al inicio de la llamada en vez de
                # la que el cliente acaba de dar.
                state.customer["address"] = address
                if state.customer.get("id"):
                    await CustomerService(self.session, self.tenant_id).update_address(state.customer["id"], address)
                    await self.session.commit()
            return

        if current == "need_payment":
            value = _match_payment(normalize_text(raw_value)) or normalize_text(raw_value)
            if value not in {"efectivo", "yape", "plin", "tarjeta"}:
                return
            state.payment_method = value

    def _build_summary(self, state: ConversationState) -> str:
        lines = [
            f"{item.quantity} {speakify_product_name(item.name)}" + (f" ({item.notes})" if item.notes else "")
            for item in state.items
        ]
        total = sum(item.quantity * item.unit_price for item in state.items)
        time_part = f" para las {state.requested_time}" if state.requested_time else ""

        if state.fulfillment_type == "delivery":
            place_part = f", delivery a {state.delivery_address}" if state.delivery_address else ", por delivery"
        elif state.fulfillment_type == "pickup":
            place_part = ", recojo en el local"
        else:
            place_part = ""

        payment_part = f", pagas con {state.payment_method}" if state.payment_method else ""
        name = state.customer.get("name") if state.customer else None
        name_part = f" A nombre de {name}." if name else ""

        return (
            f"Perfecto: {', '.join(lines)}. Son {_format_money_for_voice(total)}{time_part}{place_part}{payment_part}."
            f"{name_part} ¿Confirmas?"
        )

    async def _confirm_order(self, state: ConversationState, tool_calls: list[ToolCallOut]) -> OrderOut | None:
        context: dict = {
            # .get(), no state.customer["id"]: un cliente sin telefono (chat
            # web sin dar numero, o llamada con ID oculto) que despues da su
            # nombre por voz llega aca con un dict {"name": ...} SIN "id" --
            # ver _apply_detail_answer("need_name"). El acceso con corchetes
            # tiraba KeyError y hacia caer la confirmacion entera del pedido.
            # Reproducido en vivo antes de este fix.
            "customer_id": state.customer.get("id") if state.customer else None,
            "conversation_id": state.id,
            "requested_time": state.requested_time,
            "fulfillment_type": state.fulfillment_type,
            "delivery_address": state.delivery_address,
            "payment_method": state.payment_method,
            "channel": "whatsapp",  # canal de la notificacion de confirmacion, no el de la conversacion
            "items": [
                {"product_id": item.product_id, "quantity": item.quantity, "notes": item.notes}
                for item in state.items
            ],
        }
        engine = WorkflowEngine(self.tools)
        run_result = await engine.run(RESTAURANT_ORDER_FULFILLMENT, context)

        for step in run_result.trace:
            if step.tool:
                tool_calls.append(
                    ToolCallOut(name=step.tool, arguments=step.arguments or {}, result=step.result or {"error": step.detail})
                )

        await self._persist_workflow_run(run_result)

        if run_result.status != "completed":
            state.unresolved.append(run_result.error or "error desconocido")
            return None

        _reset_order_draft(state)
        # Releemos el pedido en vez de reusar el dict capturado tras crearlo:
        # los pasos siguientes del workflow (schedule_delivery) lo modifican
        # (status pasa a "scheduled"), y la respuesta al usuario debe reflejar
        # el estado final, no una foto intermedia.
        order_id = run_result.context["order_result"]["order"]["id"]
        return await OrderService(self.session, self.tenant_id).get(order_id)

    async def _persist_workflow_run(self, run_result: WorkflowRunResult) -> None:
        self.session.add(
            WorkflowRun(
                tenant_id=self.tenant_id,
                workflow_key=run_result.workflow_key,
                status=run_result.status,
                context_snapshot=json.dumps(run_result.context, ensure_ascii=False, default=str),
                trace=json.dumps([asdict(step) for step in run_result.trace], ensure_ascii=False, default=str),
            )
        )
        await self.session.commit()

    async def _finish(
        self,
        state: ConversationState,
        response: str,
        intent: str,
        missing: list[str],
        tool_calls: list[ToolCallOut],
        order: OrderOut | None,
    ) -> AgentTurnOut:
        state.transcript.append(_transcript_line("agente", response))
        await self._persist_conversation(state, intent)
        await self._persist_turn_metric(state, intent)
        return AgentTurnOut(
            response=response, intent=intent, missing=missing, tool_calls=tool_calls,
            order=order, conversation_id=state.id, status=state.status,
        )

    async def _persist_turn_metric(self, state: ConversationState, intent: str) -> None:
        # Observabilidad: cuanto tardo AgentRuntime en este turno especifico.
        # No debe poder tumbar un turno real si algo sale mal aca -- es
        # metrica, no logica de negocio -- por eso el try/except propio en
        # vez de dejar que una excepcion aca reviente la respuesta al cliente.
        if state.turn_started_at is None:
            return
        think_ms = int((time.monotonic() - state.turn_started_at) * 1000)
        try:
            self.session.add(
                VoiceTurnMetric(
                    tenant_id=self.tenant_id,
                    conversation_id=state.id,
                    channel=state.channel,
                    intent=intent,
                    status=state.status,
                    think_ms=max(think_ms, 0),
                    used_fallback=state.used_fallback_this_turn,
                )
            )
            await self.session.commit()
        except Exception:
            logger.exception("No se pudo guardar VoiceTurnMetric conversation_id=%s", state.id)

    async def _persist_conversation(self, state: ConversationState, intent: str) -> None:
        convo = await self.session.scalar(
            select(Conversation).where(
                Conversation.tenant_id == self.tenant_id, Conversation.external_id == state.id
            )
        )
        transcript_text = "\n".join(state.transcript)
        customer_id = state.customer.get("id") if state.customer else None  # ver nota en _confirm_order
        db_status = "closed" if state.status == "closed" else "active"

        if convo:
            convo.transcript = transcript_text
            convo.customer_id = customer_id
            convo.status = db_status
            convo.detail_status = state.status
            if state.status == "closed":
                convo.outcome = intent
        else:
            convo = Conversation(
                tenant_id=self.tenant_id,
                external_id=state.id,
                customer_id=customer_id,
                channel=state.channel,
                status=db_status,
                detail_status=state.status,
                transcript=transcript_text,
                outcome=intent if state.status == "closed" else None,
            )
            self.session.add(convo)
        await self.session.commit()
