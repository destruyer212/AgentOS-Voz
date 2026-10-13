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
from app.domain.delivery_zones import (
    address_names_known_district,
    ask_district_message,
    delivery_zone_rejection_message,
)
from app.domain.invoicing_schemas import InvoiceFromOrderRequest, InvoiceOut
from app.domain.invoicing_services import InvoicingError, InvoicingService
from app.domain.models import Conversation, Tenant, VoiceTurnMetric, WorkflowRun
from app.domain.order_review import build_review_link
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
from app.infrastructure.db.session import AsyncSessionLocal
from app.integrations import apiperu_client
from app.integrations.wsp_notifications import (
    fire_and_forget,
    notify_order_confirmed,
    notify_order_review_link,
)
from app.tools.registry import ToolRegistry
from app.workflows.definitions import RESTAURANT_ORDER_FULFILLMENT
from app.workflows.engine import WorkflowEngine
from app.workflows.models import WorkflowRunResult

# Sub-estados de recoleccion de datos de entrega, en el orden en que se piden.
logger = logging.getLogger(__name__)

_DETAIL_STATUSES = (
    "need_name",
    "need_fulfillment",
    "need_address",
    "need_payment",
    "need_yape_code",
    "need_document",
    "need_dni",
    "need_ruc",
)

_DETAIL_PROMPTS = {
    "name": "Para el pedido, ¿a nombre de quién lo dejo?",
    "fulfillment": "¿Lo recoges tú en el local o te lo llevamos por delivery?",
    "address": "¿Cuál es la dirección de entrega?",
    "payment": "¿Pagas en efectivo, Yape o tarjeta?",
    # Pedido explicito: "codigo de aprobacion" de Yape (el codigo de
    # seguridad de 3 digitos que Yape le muestra a quien paga Y a quien
    # recibe, pensado para frenar "yapeos falsos"). Aca NO se verifica
    # contra ninguna API real de Yape -- solo se valida el formato (3
    # digitos) y se guarda, para que el negocio lo cruce a mano contra su
    # propio Yape. A proposito se responde como si fuera una verificacion
    # real (ver "Listo, pago concretado." en _advance_order) para que la
    # llamada se sienta igual de seria que pedir el DNI.
    "yape_code": "Perfecto, pagas con Yape. ¿Me dictas el código de aprobación? Son 3 dígitos.",
    "document": "¿Quieres boleta o factura?",
    "dni": "Perfecto, para la boleta me dictas tu DNI, por favor. Son 8 dígitos.",
    "ruc": "Perfecto, ¿me dictas el RUC de tu empresa? Son 11 dígitos.",
}

# Palabras que, en cualquier punto de la conversacion, indican que el
# cliente quiere factura (con RUC) en vez de la boleta automatica por
# defecto -- ver domain/invoicing_services.py. Deliberadamente simple
# (substring, no NLU): una vez detectado no hace falta reconocerlo de
# nuevo, y una falsa alarma solo agrega una pregunta de mas, nunca rompe
# el pedido.
_FACTURA_REQUEST_PHRASES = ("factura", "con ruc", "facturar", "a nombre de mi empresa", "a nombre de la empresa")

_DNI_RE = re.compile(r"(?<!\d)(\d{8})(?!\d)")
_RUC_RE = re.compile(r"(?<!\d)(\d{11})(?!\d)")

# Bug real, visto en vivo: al pedir el DNI, la gente en Peru casi nunca
# dicta 8 digitos seguidos como numero unico -- lo dice en grupos hablados
# ("Setenta, ochenta y uno, treinta y uno, cincuenta y dos" -> 70-81-31-52)
# o digito por digito ("Siete cero ocho uno tres uno cinco dos"). Deepgram
# transcribe esos numeros como PALABRAS, no como digitos, asi que
# _DNI_RE/_RUC_RE (que solo buscan caracteres 0-9) nunca los reconocian --
# la llamada real terminaba colgada en un loop pidiendo el DNI de nuevo y
# de nuevo sin exito. _spoken_digit_groups() convierte cada palabra-numero
# (0-99) a su valor y las junta en orden para formar el numero completo,
# sin importar en que agrupacion las haya dicho el cliente.
_SPANISH_UNITS = {
    "cero": "0", "uno": "1", "una": "1", "dos": "2", "tres": "3", "cuatro": "4",
    "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9",
}
_SPANISH_TEENS = {
    "diez": "10", "once": "11", "doce": "12", "trece": "13", "catorce": "14",
    "quince": "15", "dieciseis": "16", "diecisiete": "17", "dieciocho": "18",
    "diecinueve": "19",
}
_SPANISH_TWENTIES_FUSED = {
    "veintiuno": "21", "veintidos": "22", "veintitres": "23", "veinticuatro": "24",
    "veinticinco": "25", "veintiseis": "26", "veintisiete": "27", "veintiocho": "28",
    "veintinueve": "29",
}
_SPANISH_TENS = {
    "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50,
    "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90,
}


def _spoken_digit_groups(text: str) -> str:
    """Concatena, en orden, cada numero (0-99) encontrado en `text` -- ya
    sea escrito en digitos ("81") o dicho en palabras ("ochenta y uno") --
    ignorando cualquier otra palabra (comas, "y" de conexion, "mi dni es",
    etc). Solo cubre 0-99 a proposito: un DNI/RUC nunca se dicta con
    "cientos"/"miles", siempre en grupos de 1-2 digitos."""
    tokens = normalize_text(text).split()
    groups: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.isdigit():
            groups.append(token)
            i += 1
        elif token in _SPANISH_TWENTIES_FUSED:
            groups.append(_SPANISH_TWENTIES_FUSED[token])
            i += 1
        elif token in _SPANISH_TENS:
            if i + 2 < len(tokens) and tokens[i + 1] == "y" and tokens[i + 2] in _SPANISH_UNITS:
                groups.append(str(_SPANISH_TENS[token] + int(_SPANISH_UNITS[tokens[i + 2]])))
                i += 3
            else:
                groups.append(str(_SPANISH_TENS[token]))
                i += 1
        elif token in _SPANISH_TEENS:
            groups.append(_SPANISH_TEENS[token])
            i += 1
        elif token in _SPANISH_UNITS:
            groups.append(_SPANISH_UNITS[token])
            i += 1
        else:
            i += 1
    return "".join(groups)


def _extract_id_number(raw_value: str, expected_length: int) -> str | None:
    """DNI (8 digitos), RUC (11) o codigo de aprobacion de Yape (3) desde
    una respuesta hablada. Primero intenta el caso simple (el STT ya
    entrego digitos seguidos); si no calza, intenta reconstruir el numero
    a partir de palabras habladas (ver _spoken_digit_groups). None si
    ninguna de las dos formas da exactamente la cantidad de digitos
    esperada -- nunca se acepta un numero mas largo o mas corto solo
    porque "se parece".

    Bug real: esto antes solo sabia armar el patron para 8 u 11 digitos
    (_DNI_RE/_RUC_RE) -- para cualquier otro largo (ej. el codigo de Yape
    de 3 digitos), si Deepgram transcribia los digitos seguidos ("123" en
    vez de "uno dos tres"), nunca se reconocian por este camino. El patron
    ahora se arma dinamico para el largo pedido."""
    match = re.search(rf"(?<!\d)(\d{{{expected_length}}})(?!\d)", raw_value)
    if match:
        return match.group(1)
    spoken = _spoken_digit_groups(raw_value)
    if len(spoken) == expected_length:
        return spoken
    return None


async def _lookup_document_holder_name(doc_type: str, numero: str, fallback: str) -> str:
    """DNI (doc_type "1") -> nombre completo real (RENIEC); RUC (doc_type
    "6") -> razon social real (SUNAT) -- via api.apiperu.pe (ver
    app/integrations/apiperu_client.py). Si la consulta no esta configurada
    o falla, se usa `fallback` (lo que ya se hacia antes de este lookup)
    para nunca bloquear ni romper el turno por un problema de esa API."""
    lookup = apiperu_client.lookup_dni if doc_type == "1" else apiperu_client.lookup_ruc
    resolved = await lookup(numero)
    return resolved or fallback

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

_OPTION_LABELS = ("A", "B", "C", "D", "E")


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


# Pedido explicito: cuando el agente lee "Opción A: X; Opción B: Y...", el
# cliente no siempre entiende que puede contestar solo con la letra en vez
# de repetir el nombre completo del plato -- se lo decimos explicito, una
# sola vez, al final de la pregunta.
_CLARIFICATION_ANSWER_HINT = " Me puedes responder solo con la letra."


def _format_clarification_options(options: list[dict], limit: int = 4) -> str:
    formatted = []
    for index, option in enumerate(options[:limit]):
        label = _OPTION_LABELS[index]
        product = speakify_product_name(option["name"])
        if "price" in option:
            product = f"{product} a {_format_money_for_voice(option['price'])}"
        formatted.append(f"Opción {label}: {product}")
    return "; ".join(formatted)


def _spoken_price_codes(amount: float) -> set[str]:
    """Codigos como los reconstruye _spoken_digit_groups para comparar una
    respuesta oral de precio contra una opcion del menu.

    Ej.: 28.50 -> {"2850"} porque "veintiocho soles con cincuenta" llega
    como grupos 28 + 50. Para centavos de un digito aceptamos tambien la
    forma sin cero ("cinco centimos" -> "285") ademas de "2805".
    """
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    soles = int(value)
    cents = int((value - Decimal(soles)) * 100)
    if cents == 0:
        return {str(soles)}
    return {f"{soles}{cents:02d}", f"{soles}{cents}"}


def _resolve_candidate_by_spoken_price(candidates: list[dict], message: str) -> dict | None:
    spoken = _spoken_digit_groups(message)
    if not spoken:
        return None
    exact_matches = [
        candidate
        for candidate in candidates
        if "price" in candidate and spoken in _spoken_price_codes(candidate["price"])
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        return None

    # Voz: "veinte con noventa" puede llegar como "veinte con ochenta".
    # Aceptamos una diferencia maxima de 10 centimos SOLO si deja una unica
    # opcion candidata; igual se confirma antes de agregar.
    if len(spoken) < 3 or not spoken.isdigit():
        return None
    spoken_amount = Decimal(f"{spoken[:-2]}.{spoken[-2:]}")
    fuzzy_matches = [
        candidate
        for candidate in candidates
        if "price" in candidate
        and abs(Decimal(str(candidate["price"])).quantize(Decimal("0.01")) - spoken_amount) <= Decimal("0.10")
    ]
    return fuzzy_matches[0] if len(fuzzy_matches) == 1 else None


def _option_index_from_message(message: str, option_count: int) -> int | None:
    lowered = normalize_text(message)
    if option_count <= 0:
        return None
    if re.search(r"\bultim[ao]s?\b", lowered):
        return option_count - 1

    letter_patterns = (
        (0, r"\b(?:opcion\s+a|letra\s+a|la\s+a|a)\b"),
        (1, r"\b(?:opcion\s+(?:b|be)|letra\s+(?:b|be)|la\s+(?:b|be)|(?:b|be))\b"),
        (2, r"\b(?:opcion\s+(?:c|ce)|letra\s+(?:c|ce)|la\s+(?:c|ce)|(?:c|ce))\b"),
        (3, r"\b(?:opcion\s+(?:d|de)|letra\s+(?:d|de)|la\s+(?:d|de)|(?:d|de))\b"),
        (4, r"\b(?:opcion\s+(?:e|e)|letra\s+(?:e|e)|la\s+(?:e|e)|e)\b"),
    )
    for index, pattern in letter_patterns:
        if index < option_count and re.fullmatch(pattern, lowered):
            return index
        if index < option_count and re.search(pattern, lowered) and "opcion" in lowered:
            return index

    ordinal_patterns = (
        (0, r"\b(?:primera|primero|primer|opcion\s+1|opcion\s+uno|numero\s+1|numero\s+uno)\b"),
        (1, r"\b(?:segunda|segundo|opcion\s+2|opcion\s+dos|numero\s+2|numero\s+dos)\b"),
        (2, r"\b(?:tercera|tercero|tercer|opcion\s+3|opcion\s+tres|numero\s+3|numero\s+tres)\b"),
        (3, r"\b(?:cuarta|opcion\s+4|opcion\s+cuatro|numero\s+4|numero\s+cuatro)\b"),
        (4, r"\b(?:quinta|quinto|opcion\s+5|opcion\s+cinco|numero\s+5|numero\s+cinco)\b"),
    )
    for index, pattern in ordinal_patterns:
        if index < option_count and re.search(pattern, lowered):
            return index
    return None


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


def _match_invoice_document_type(lowered: str) -> str | None:
    if any(k in lowered for k in ("factura", "ruc", "empresa", "razon social", "razón social")):
        return "factura"
    # Bug real, visto en vivo: el STT transcribio "Boleta" como "Boleto"
    # (palabra real y mucho mas comun, "boleto de avion/cine") -- sonido
    # casi identico por telefono. Sin este alias, el cliente tenia que
    # repetir "boleta" una segunda vez para que se reconociera.
    if any(k in lowered for k in ("boleta", "boleto", "dni")):
        return "boleta"
    return None


def _looks_like_fiscal_answer(current: str, message: str, lowered: str) -> bool:
    """Distingue una respuesta fiscal real de una edicion del pedido.

    En telefono, el cliente puede agregar productos incluso cuando el agente
    acaba de preguntar boleta/factura o DNI/RUC. Antes, esos turnos se
    procesaban de forma 100% determinista y "Coca Kola" se descartaba como
    respuesta invalida de comprobante. Solo tomamos la ruta fiscal si hay una
    senal clara de comprobante/documento o si el cliente esta dictando numeros.
    """
    document_type = _match_invoice_document_type(lowered)
    if current == "need_document":
        return document_type is not None

    if current == "need_dni":
        if document_type == "factura":
            return True
        return (
            _extract_id_number(message, 8) is not None
            or bool(re.search(r"\d", message))
            or "dni" in lowered
            or "documento" in lowered
            or len(_spoken_digit_groups(message)) >= 3
        )

    if current == "need_ruc":
        return (
            document_type is not None
            or _extract_id_number(message, 11) is not None
            or bool(re.search(r"\d", message))
            or len(_spoken_digit_groups(message)) >= 3
        )

    return False


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
    options = _format_clarification_options(pending.get("options") or [])
    return f"¿Cuál {query} prefieres: {options}?{_CLARIFICATION_ANSWER_HINT}" if options else None


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
    option_index = _option_index_from_message(message, len(candidates))
    if option_index is not None:
        return candidates[option_index]
    price_match = _resolve_candidate_by_spoken_price(candidates, message)
    if price_match:
        return price_match
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


def _pending_resolution_needs_confirmation(pending: dict, message: str, resolved: dict) -> bool:
    candidates = pending.get("options") or []
    option_index = _option_index_from_message(message, len(candidates))
    if option_index is not None:
        return candidates[option_index].get("id") == resolved.get("id")
    price_match = _resolve_candidate_by_spoken_price(candidates, message)
    return bool(price_match and price_match.get("id") == resolved.get("id"))


def _item_answers_pending_clarification(
    pending: dict, resolved: dict, item: ParsedItem
) -> bool:
    candidates = pending.get("options") or []
    option_index = _option_index_from_message(item.raw_text, len(candidates))
    if option_index is not None and candidates[option_index].get("id") == resolved.get("id"):
        return True
    price_match = _resolve_candidate_by_spoken_price(candidates, item.raw_text)
    if price_match and price_match.get("id") == resolved.get("id"):
        return True
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
    state.yape_approval_code = None
    state.pending_yape_code_rejection_message = None
    state.silence_retries = 0
    state.pending_clarification = None
    state.pending_clarification_confirmation = None
    state.hangup_after_response = False
    state.pending_zone_rejection_message = None
    state.pending_address_awaiting_district = None
    state.invoice_document_type = None
    state.boleta_dni = None
    state.boleta_dni_name = None
    state.wants_factura = False
    state.factura_ruc = None
    state.factura_razon_social = None
    state.pending_document_rejection_message = None
    state.pending_dni_rejection_message = None
    state.pending_ruc_rejection_message = None


async def _issue_invoice_and_notify(
    tenant_id: str,
    order_id: int,
    customer_phone: str | None,
    wants_factura: bool,
    dni: str | None,
    ruc: str | None,
    razon_social: str | None,
) -> None:
    """Corre en paralelo, fuera del turno (ver fire_and_forget en el punto
    donde se confirma el pedido): emite la boleta/factura real contra
    apisunat.pe y recien despues manda el WhatsApp de confirmacion, con el
    link al PDF si se pudo emitir. Nunca bloquea la respuesta al cliente ni
    la llamada -- si emitir el comprobante falla o tarda, el WhatsApp de
    "pedido confirmado" sale igual, solo que sin el link.

    Sesion de DB propia (AsyncSessionLocal, no self.session): para cuando
    esto corre, la sesion del turno que disparo la llamada ya pudo haberse
    cerrado -- mismo motivo por el que notify_order_confirmed no toca la
    sesion del turno en absoluto."""
    document_url: str | None = None
    document_label: str | None = None
    async with AsyncSessionLocal() as session:
        try:
            document_type = "factura" if wants_factura else "boleta"
            request = InvoiceFromOrderRequest(
                order_id=order_id,
                document_type=document_type,
                cliente_tipo_doc="6" if wants_factura else None,
                cliente_numero_doc=ruc if wants_factura else dni,
                cliente_denominacion=razon_social if wants_factura else None,
            )
            if not wants_factura and dni:
                request.cliente_tipo_doc = "1"
            invoice: InvoiceOut = await InvoicingService(session, tenant_id).create_from_order(request)
            if invoice.sunat_pdf_a4_url:
                label = "Factura" if wants_factura else "Boleta"
                document_url = invoice.sunat_pdf_a4_url
                document_label = f"{label} {invoice.serie}-{invoice.numero}"
        except InvoicingError:
            logger.exception("No se pudo emitir comprobante SUNAT para order_id=%s", order_id)
        except Exception:
            logger.exception("Fallo inesperado emitiendo comprobante SUNAT para order_id=%s", order_id)

        order_out = await OrderService(session, tenant_id).get(order_id)

    whatsapp_status = await notify_order_confirmed(
        order_out, customer_phone, document_url=document_url, document_label=document_label
    )
    async with AsyncSessionLocal() as session:
        await OrderService(session, tenant_id).record_whatsapp_status(order_id, whatsapp_status)


async def _notify_only(tenant_id: str, order_id: int, customer_phone: str | None) -> None:
    """Mismo aviso de "pedido confirmado" que _issue_invoice_and_notify,
    pero sin intentar emitir ningun comprobante -- para tenants que todavia
    no configuraron su token de apisunat.pe (ver el punto donde se confirma
    el pedido: ahi se decide cual de las dos correr).

    Corte temprano si wsp-service tampoco esta configurado: sin eso no hay
    nada real que trackear (notify_order_confirmed devolveria
    "skipped_not_configured" de todos modos), y evita abrir sesiones de DB
    de mas en cada pedido confirmado -- importa sobre todo en tests, que
    corren todos contra el mismo archivo SQLite compartido y no tienen ni
    apisunat_token ni wsp-service configurados: sin este corte, cada pedido
    confirmado en CUALQUIER test disparaba dos sesiones de background
    peleando por el mismo archivo con la sesion del test ("database is
    locked")."""
    if not settings.wsp_service_url or not settings.wsp_service_api_key:
        return
    async with AsyncSessionLocal() as session:
        order_out = await OrderService(session, tenant_id).get(order_id)
    whatsapp_status = await notify_order_confirmed(order_out, customer_phone)
    async with AsyncSessionLocal() as session:
        await OrderService(session, tenant_id).record_whatsapp_status(order_id, whatsapp_status)


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

        if state.pending_clarification_confirmation:
            return await self._handle_pending_clarification_confirmation(
                state, payload.message, tool_calls
            )

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

        # Pedido de factura: puede llegar en cualquier momento (junto con el
        # pedido, a mitad de dar los datos, o incluso despues de ya ver el
        # resumen final). Por defecto el pedido se factura solo como boleta
        # (sin preguntar nada nuevo) -- esto solo prende el flag y, si ya
        # estabamos esperando el "si, confirmo" final, interrumpe para pedir
        # el RUC antes de seguir (si no, la boleta ya se habria armado sin
        # el RUC). En cualquier otro momento simplemente sigue el turno
        # normal -- _next_missing_detail agrega la pregunta del RUC sola
        # cuando le toque, sin necesidad de cortar el flujo aca.
        if not state.wants_factura and any(
            phrase in normalize_text(payload.message) for phrase in _FACTURA_REQUEST_PHRASES
        ):
            state.wants_factura = True
            state.invoice_document_type = "factura"
            if state.status == "awaiting_confirmation" and not state.factura_ruc:
                state.status = "need_ruc"
                return await self._finish(state, _DETAIL_PROMPTS["ruc"], "detail.ask", [], tool_calls, None)

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

        # Bug real, visto en vivo: con una aclaracion pendiente ("Cual
        # cuarto de pollo prefieres...?"), "¿Puede repetir, por favor?"
        # parseaba como order.create (no como smalltalk), asi que el
        # manejo especifico de "repiteme la pregunta" (mas abajo, atado a
        # smalltalk+telefono) nunca se activaba -- se buscaba como
        # PRODUCTO ("No encontre ¿Puede repetir en el menu") y se perdia
        # la pregunta pendiente. Se revisa ANTES de mirar el intent, para
        # cualquier canal.
        if state.pending_clarification and is_audio_repair_message(payload.message):
            clarification = _pending_clarification_question(state)
            if clarification:
                return await self._finish(state, clarification, "smalltalk", [], tool_calls, None)

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

            missing, clarifications, added = await self._normalize_items(state, parsed.items, tool_calls)
            if parsed.requested_time:
                state.requested_time = parsed.requested_time

            if clarifications:
                state.status = "collecting"
                return await self._finish(state, " ".join(clarifications), "order.clarify", missing, tool_calls, None)

            if missing:
                state.status = "collecting"
                # Bug real, visto en vivo: si el mensaje traia otro item que
                # SI se agrego bien (ej. "Salvan negro y torta de
                # chocolate." -> "torta de chocolate" entraba sola), la
                # respuesta vieja solo hablaba de lo que fallo -- el cliente
                # nunca se enteraba que la otra parte ya habia entrado y la
                # repetia en el turno siguiente, duplicandola. Se confirma
                # primero lo que si se agrego.
                ack = f"Agregué {', '.join(added)}. " if added else ""
                response = ack + "No encontré " + "; ".join(missing) + " en el menú. ¿Me lo repites o pides otra cosa?"
                return await self._finish(state, response, "order.create", missing, tool_calls, None)

            if not state.items:
                return await self._finish(
                    state, "No te entendí bien. ¿Qué te gustaría pedir?",
                    "order.create", [], tool_calls, None,
                )

            return await self._advance_order(state, tool_calls)

        if parsed.intent == "order.confirm" and state.status == "awaiting_confirmation":
            # Capturados ANTES de _confirm_order: ese metodo llama
            # _reset_order_draft al confirmar, que ya deja el flag y el RUC
            # en blanco para el proximo pedido de la misma llamada -- si se
            # leyeran despues, siempre saldria boleta sin RUC.
            wants_factura = state.wants_factura
            boleta_dni = state.boleta_dni
            factura_ruc = state.factura_ruc
            factura_razon_social = state.factura_razon_social

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
            # Dispara en paralelo, sin esperar: primero emite la boleta/
            # factura real contra apisunat.pe y recien despues manda el
            # WhatsApp de confirmacion (con el link al PDF si se pudo
            # emitir). Si SUNAT esta lento o caido, la llamada igual sigue y
            # cuelga normal -- ver _issue_invoice_and_notify. Solo se
            # dispara si el negocio configuro su token de apisunat.pe: sin
            # eso, ni siquiera se crea el borrador local -- evita llenar la
            # tabla de comprobantes (y gastar numeros de serie) para
            # negocios que todavia no activaron facturacion electronica.
            customer_phone = state.customer.get("phone") if state.customer else None
            tenant = await self.session.get(Tenant, self.tenant_id)
            if tenant and tenant.apisunat_token:
                fire_and_forget(
                    _issue_invoice_and_notify(
                        self.tenant_id,
                        order.id,
                        customer_phone,
                        wants_factura,
                        boleta_dni,
                        factura_ruc,
                        factura_razon_social,
                    )
                )
            else:
                fire_and_forget(_notify_only(self.tenant_id, order.id, customer_phone))
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
        state.customer = {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "address": customer.address,
            "doc_type": customer.doc_type,
            "doc_number": customer.doc_number,
            "legal_name": customer.legal_name,
        }
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
    ) -> tuple[list[str], list[str], list[str]]:
        missing: list[str] = []
        clarifications: list[str] = []
        # Bug real, visto en vivo: "Salvan negro y torta de chocolate." ->
        # "torta de chocolate" SI se agregaba, pero la respuesta solo decia
        # "No encontre Salvan negro" -- el cliente nunca se enteraba que la
        # otra parte ya habia entrado, asi que en el turno siguiente volvia
        # a decir la frase completa y "Torta de Chocolate" terminaba
        # duplicada en el pedido. Se junta el nombre (hablado) de cada item
        # que SI se agrego en este turno para poder confirmarlo en la
        # respuesta, no solo lo que fallo.
        added: list[str] = []
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
                    if _pending_resolution_needs_confirmation(
                        state.pending_clarification, item.raw_text, resolved
                    ):
                        state.pending_clarification_confirmation = {
                            "product": resolved,
                            "quantity": item.quantity,
                            "notes": item.notes,
                        }
                        clarifications.append(
                            f"Creo que es {speakify_product_name(resolved['name'])} "
                            f"a {_format_money_for_voice(resolved['price'])}. ¿Confirmas, sí o no?"
                        )
                        continue
                    state.pending_clarification = None
                    self._add_or_increment_item(state, resolved, item.quantity, item.notes)
                    added.append(f"{item.quantity} {speakify_product_name(resolved['name'])}")
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
                        option_names = _format_clarification_options(options, limit=5)
                        clarifications.append(
                            f"En {label} tenemos: {option_names}. ¿Cuál prefieres?{_CLARIFICATION_ANSWER_HINT}"
                        )
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
                options = _format_clarification_options(candidates, limit=4)
                clarifications.append(f"¿Cuál {item.query} prefieres: {options}?{_CLARIFICATION_ANSWER_HINT}")
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
            added.append(f"{item.quantity} {speakify_product_name(best['name'])}")
        return missing, clarifications, added

    async def _handle_pending_clarification_confirmation(
        self, state: ConversationState, message: str, tool_calls: list[ToolCallOut]
    ) -> AgentTurnOut:
        pending_confirmation = state.pending_clarification_confirmation or {}
        product = pending_confirmation.get("product")
        if not product:
            state.pending_clarification_confirmation = None
            return await self._finish(
                state, "No te entendí bien. ¿Me repites cuál opción quieres?", "order.clarify", [], tool_calls, None
            )

        words = set(normalize_text(message).split())
        if words and words <= CONFIRM_WORDS:
            state.pending_clarification_confirmation = None
            state.pending_clarification = None
            quantity = int(pending_confirmation.get("quantity") or 1)
            notes = pending_confirmation.get("notes")
            self._add_or_increment_item(state, product, quantity, notes)
            return await self._advance_order(state, tool_calls)

        if words & CANCEL_WORDS:
            state.pending_clarification_confirmation = None
            clarification = _pending_clarification_question(state)
            response = clarification or "Ok, ¿cuál opción prefieres entonces?"
            return await self._finish(state, response, "order.clarify", [], tool_calls, None)

        response = (
            f"Para no equivocarme: ¿confirmas que quieres "
            f"{speakify_product_name(product['name'])}, sí o no?"
        )
        return await self._finish(state, response, "order.clarify", [], tool_calls, None)

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
        # Codigo de aprobacion "ficticio" de Yape -- ver _DETAIL_PROMPTS
        # ["yape_code"]: solo se pide si pago es Yape, nunca para
        # efectivo/tarjeta.
        if state.payment_method == "yape" and not state.yape_approval_code:
            return "yape_code"
        if state.channel == "phone" and not state.invoice_document_type:
            return "document"
        # El DNI obligatorio de la boleta es solo para voz (ver
        # _DETAIL_PROMPTS["document"] y el pedido explicito del negocio: "en
        # la voz pregunte boleta o factura"). En web/WhatsApp, aunque
        # invoice_document_type termine en "boleta" (ej. un cliente que se
        # arrepintio de pedir factura, ver need_ruc mas abajo), la boleta
        # sigue siendo automatica con el placeholder de apisunat.pe -- no se
        # le exige DNI a nadie que no llamo por telefono.
        if state.channel == "phone" and state.invoice_document_type == "boleta" and not state.boleta_dni:
            return "dni"
        if state.wants_factura and not state.factura_ruc:
            return "ruc"
        return None

    async def _advance_order(self, state: ConversationState, tool_calls: list[ToolCallOut]) -> AgentTurnOut:
        """Una vez que los items del pedido estan completos, pide los datos
        que falten (nombre, delivery/recojo, direccion, forma de pago) antes
        de pasar al resumen final. Un dato a la vez, en orden fijo."""
        # "Listo, pago concretado." -- ver _DETAIL_PROMPTS["yape_code"]: se
        # antepone a lo que sea que venga despues, UNA sola vez, justo
        # cuando el codigo de Yape se acaba de capturar bien (nunca si hubo
        # que rechazarlo y pedirlo de nuevo -- ahi gana el mensaje de
        # rechazo de abajo).
        confirm_yape_prefix = (
            "Listo, pago concretado. "
            if state.status == "need_yape_code" and not state.pending_yape_code_rejection_message
            else ""
        )
        missing_detail = self._next_missing_detail(state)
        if missing_detail:
            state.status = f"need_{missing_detail}"
            prompt = _DETAIL_PROMPTS[missing_detail]
            if missing_detail == "address" and state.pending_zone_rejection_message:
                prompt = state.pending_zone_rejection_message
            elif missing_detail == "document" and state.pending_document_rejection_message:
                prompt = state.pending_document_rejection_message
            elif missing_detail == "dni" and state.pending_dni_rejection_message:
                prompt = state.pending_dni_rejection_message
            elif missing_detail == "ruc" and state.pending_ruc_rejection_message:
                prompt = state.pending_ruc_rejection_message
            elif missing_detail == "yape_code" and state.pending_yape_code_rejection_message:
                prompt = state.pending_yape_code_rejection_message
            return await self._finish(state, f"{confirm_yape_prefix}{prompt}", "order.create", [], tool_calls, None)
        state.status = "awaiting_confirmation"
        self._maybe_send_review_link(state)
        return await self._finish(
            state, f"{confirm_yape_prefix}{self._build_summary(state)}", "order.create", [], tool_calls, None
        )

    @staticmethod
    def _maybe_send_review_link(state: ConversationState) -> None:
        """Carrito visual durante la llamada (ver
        docs/08-mejora-carrito-visual-en-llamada.md) -- unico punto de
        enganche de esa feature con el runtime real. Solo por telefono
        (web/WhatsApp ya VEN el pedido en su propia pantalla/chat, no hace
        falta un link aparte) y solo una vez por llamada (ver
        ConversationState.review_link_sent). Si no hay telefono del
        cliente todavia, notify_order_review_link se encarga de saltarlo
        en silencio -- esto nunca debe poder demorar ni romper el turno
        real, por eso fire_and_forget()."""
        if state.channel != "phone" or state.review_link_sent:
            return
        phone = state.customer.get("phone") if state.customer else None
        if not phone:
            return
        state.review_link_sent = True
        subtotal = sum(item.quantity * item.unit_price for item in state.items)
        delivery_fee = settings.delivery_fee_soles if state.fulfillment_type == "delivery" else 0.0
        fire_and_forget(
            notify_order_review_link(
                state.id,
                state.customer.get("name") if state.customer else None,
                phone,
                build_review_link(state.id),
                [
                    {"name": item.name, "quantity": item.quantity, "unit_price": item.unit_price}
                    for item in state.items
                ],
                round(subtotal + delivery_fee, 2),
                state.fulfillment_type,
                state.delivery_address,
                state.payment_method,
            )
        )

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

        payment_match = _match_payment(lowered) if current == "need_payment" else None

        # Cancelar sigue disponible en cualquier momento, incluso a mitad de
        # esta recoleccion de datos. Pero en voz no tratamos un "no" suelto
        # como cancelacion si el mismo turno trae una forma de pago clara:
        # Deepgram puede transcribir "con Yape, pues" como "con Yape ... no".
        if words & CANCEL_WORDS and not payment_match:
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

        # Ruta dedicada para cuando se acaba de preguntar explicitamente el
        # distrito (ver _apply_detail_answer/need_address y
        # domain/delivery_zones.py). La respuesta ahi suele ser una sola
        # palabra ("Comas", "Ancón") -- el camino generico de mas abajo
        # (literal/NLU) exige 2+ palabras o un digito para aceptar una
        # direccion, asi que un distrito suelto se perderia y volveria a
        # preguntar en loop. Se acepta directo salvo que la respuesta traiga
        # señales claras de ser otra cosa (pedir/cambiar del menu).
        if current == "need_address" and state.pending_address_awaiting_district and not any(
            word in lowered for word in _DETAIL_LITERAL_BLOCKLIST
        ):
            await self._apply_detail_answer(state, current, message)
            return await self._advance_order(state, tool_calls)

        # Comprobante y documento fiscal: si el turno trae una respuesta
        # fiscal clara, se procesa deterministamente. Si no, dejamos que el
        # parser intente tratarlo como edicion del pedido antes de rechazarlo
        # como DNI/RUC/documento invalido. Caso real: al preguntar "boleta o
        # factura", el cliente dijo "Coca Kola"; eso debe agregar la bebida y
        # luego repetir la pregunta fiscal, no perder el item.
        if current in {"need_document", "need_dni", "need_ruc"} and _looks_like_fiscal_answer(
            current, message, lowered
        ):
            await self._apply_detail_answer(state, current, message)
            return await self._advance_order(state, tool_calls)

        # Codigo de aprobacion de Yape: mismo criterio que arriba -- si el
        # turno trae digitos (seguidos o hablados), es un intento de dar el
        # codigo, se procesa directo. Si no trae ningun digito, puede ser
        # que el cliente este agregando algo al pedido ("tambien quiero una
        # Coca Kola") -- se deja caer al flujo normal de abajo para no
        # perder el item, igual que con boleta/factura/DNI/RUC.
        if current == "need_yape_code" and (
            bool(re.search(r"\d", message)) or len(_spoken_digit_groups(message)) >= 1
        ):
            await self._apply_detail_answer(state, current, message)
            return await self._advance_order(state, tool_calls)

        # Ruta ultrarrapida y segura: fulfillment/pago son vocabularios
        # cerrados. Si calzan directo, no llamamos a Gemini.
        if current == "need_fulfillment":
            match = _match_fulfillment(lowered)
            if match:
                await self._apply_detail_answer(state, current, match)
                return await self._advance_order(state, tool_calls)
        elif current == "need_payment":
            match = payment_match
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
            missing, clarifications, _added = await self._normalize_items(state, parsed.items, tool_calls)

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

        if current in {"need_document", "need_dni", "need_ruc", "need_yape_code"}:
            await self._apply_detail_answer(state, current, message)
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
                # La direccion guardada en la ficha del cliente tambien pasa
                # por el mismo chequeo de zona/distrito que una direccion
                # nueva -- si no, un cliente repetido con una direccion vieja
                # sin distrito (o de fuera de zona) se saltaria el filtro por
                # completo. Si no pasa, NO se autocompleta: se deja
                # delivery_address vacio para que _next_missing_detail vuelva
                # a preguntar, con el mensaje correcto ya listo.
                saved_address = state.customer["address"]
                zone_message = delivery_zone_rejection_message(saved_address)
                if zone_message:
                    state.pending_zone_rejection_message = zone_message
                elif not address_names_known_district(saved_address):
                    state.pending_address_awaiting_district = saved_address
                    state.pending_zone_rejection_message = ask_district_message()
                else:
                    state.delivery_address = saved_address
            return

        if current == "need_address":
            address = _extract_address(raw_value)
            # Si ya estabamos esperando el distrito de una direccion previa
            # (ver mas abajo), esta respuesta es SOLO el distrito -- se junta
            # con la calle que ya habian dado en vez de tratarla como una
            # direccion nueva que la reemplaza (si no, "San Martin de Porres"
            # solo pisaria el "Jr. Las Flores 123" ya dado). Ya se pregunto
            # una vez, asi que esta es la ultima oportunidad: si la respuesta
            # tampoco trae un distrito reconocible, se deja pasar tal cual en
            # vez de preguntar de nuevo (mejor no trabar a un cliente real de
            # la zona en un loop infinito).
            already_asked_district = bool(state.pending_address_awaiting_district)
            if already_asked_district:
                address = f"{state.pending_address_awaiting_district}, {raw_value}"
                state.pending_address_awaiting_district = None

            # Pedido explicito del negocio: delivery solo cerca de Puente
            # Piedra, nunca fuera de Lima. Si la direccion da evidencia de
            # estar fuera de zona, no se guarda -- se deja el mensaje listo
            # para que _advance_order lo repita en vez de la pregunta
            # generica de direccion (sigue pidiendola hasta que den una
            # valida o cambien a recojo en el local).
            zone_message = delivery_zone_rejection_message(address)
            if zone_message:
                state.pending_zone_rejection_message = zone_message
                return

            # La direccion no menciona ningun distrito conocido (ni cercano
            # ni lejano) -- no hay con que decidir si esta en zona. En vez de
            # dejarla pasar en silencio (lo que dejaria entrar direcciones
            # fuera de zona que nunca nombran su distrito), se pregunta el
            # distrito explicitamente una vez.
            if not already_asked_district and not address_names_known_district(address):
                state.pending_address_awaiting_district = address
                state.pending_zone_rejection_message = ask_district_message()
                return

            state.pending_zone_rejection_message = None
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
            # Si se arrepintio y cambio de Yape a otra cosa, el codigo ya
            # no aplica -- mismo motivo que factura_ruc se limpia al volver
            # a boleta.
            if value != "yape":
                state.yape_approval_code = None
                state.pending_yape_code_rejection_message = None
            return

        if current == "need_yape_code":
            # Codigo de aprobacion "ficticio" de Yape -- ver
            # _DETAIL_PROMPTS["yape_code"]: no se verifica contra ninguna
            # API real de Yape (no la tenemos integrada), solo se valida el
            # formato (3 digitos exactos, igual de estricto que el DNI/RUC)
            # y se guarda para que el negocio lo cruce a mano.
            code = _extract_id_number(raw_value, 3)
            if not code:
                state.pending_yape_code_rejection_message = (
                    "No reconocí el código. Son 3 dígitos, ¿me lo repites?"
                )
                return
            state.yape_approval_code = code
            state.pending_yape_code_rejection_message = None
            return

        if current == "need_document":
            document_type = _match_invoice_document_type(normalize_text(raw_value))
            if document_type not in {"boleta", "factura"}:
                state.pending_document_rejection_message = "No te entendí bien. ¿Quieres boleta o factura?"
                return

            state.invoice_document_type = document_type
            state.wants_factura = document_type == "factura"
            state.pending_document_rejection_message = None
            if document_type == "boleta":
                state.factura_ruc = None
                state.factura_razon_social = None
                dni = _extract_id_number(raw_value, 8)
                if dni:
                    state.boleta_dni = dni
                    state.pending_dni_rejection_message = None
                    legal_name = await _lookup_document_holder_name("1", dni, "") or None
                    state.boleta_dni_name = legal_name
                    if state.customer:
                        state.customer["doc_type"] = "1"
                        state.customer["doc_number"] = state.boleta_dni
                        state.customer["legal_name"] = legal_name
                        if state.customer.get("id"):
                            await CustomerService(self.session, self.tenant_id).update_tax_info(
                                state.customer["id"], "1", state.boleta_dni, legal_name
                            )
                            await self.session.commit()
            else:
                state.boleta_dni = None
                state.boleta_dni_name = None
                ruc = _extract_id_number(raw_value, 11)
                if ruc:
                    fallback_name = (state.customer.get("name") if state.customer else None) or "CLIENTE"
                    razon_social = await _lookup_document_holder_name("6", ruc, fallback_name)
                    state.factura_ruc = ruc
                    state.factura_razon_social = razon_social
                    state.pending_ruc_rejection_message = None
                    if state.customer:
                        state.customer["doc_type"] = "6"
                        state.customer["doc_number"] = state.factura_ruc
                        state.customer["legal_name"] = razon_social
                        if state.customer.get("id"):
                            await CustomerService(self.session, self.tenant_id).update_tax_info(
                                state.customer["id"], "6", state.factura_ruc, razon_social
                            )
                            await self.session.commit()
            return

        if current == "need_dni":
            lowered = normalize_text(raw_value)
            if _match_invoice_document_type(lowered) == "factura" and not _extract_id_number(raw_value, 8):
                state.invoice_document_type = "factura"
                state.wants_factura = True
                state.boleta_dni = None
                state.boleta_dni_name = None
                state.pending_dni_rejection_message = None
                return
            dni = _extract_id_number(raw_value, 8)
            if not dni:
                state.pending_dni_rejection_message = (
                    "No reconocí un DNI válido. Para boleta son exactamente 8 dígitos. ¿Me lo repites?"
                )
                return
            state.invoice_document_type = "boleta"
            state.wants_factura = False
            state.boleta_dni = dni
            state.pending_dni_rejection_message = None
            legal_name = await _lookup_document_holder_name("1", dni, "") or None
            state.boleta_dni_name = legal_name
            if state.customer:
                state.customer["doc_type"] = "1"
                state.customer["doc_number"] = dni
                state.customer["legal_name"] = legal_name
                if state.customer.get("id"):
                    await CustomerService(self.session, self.tenant_id).update_tax_info(
                        state.customer["id"], "1", dni, legal_name
                    )
                    await self.session.commit()
            return

        if current == "need_ruc":
            lowered = normalize_text(raw_value)
            # Se arrepintio y prefiere boleta -- vuelve al flujo normal sin
            # trabarse pidiendo un RUC que ya no quiere dar; en voz igual se
            # pedira el DNI obligatorio de la boleta.
            if "boleta" in lowered and not _extract_id_number(raw_value, 11):
                state.invoice_document_type = "boleta"
                state.wants_factura = False
                state.pending_ruc_rejection_message = None
                dni = _extract_id_number(raw_value, 8)
                if dni:
                    state.boleta_dni = dni
                    state.boleta_dni_name = await _lookup_document_holder_name("1", dni, "") or None
                    state.pending_dni_rejection_message = None
                return
            ruc = _extract_id_number(raw_value, 11)
            if not ruc:
                state.pending_ruc_rejection_message = (
                    "No reconocí un RUC válido. Para factura son exactamente 11 dígitos. ¿Me lo repites, o prefieres boleta?"
                )
                return
            # La razon social REAL viene de api.apiperu.pe (ver
            # _lookup_document_holder_name / apiperu_client.py) -- el
            # fallback de abajo (lo que sobra del mensaje despues de sacar
            # el RUC y palabras de relleno tipicas, o el nombre que ya dio
            # el cliente) solo se usa si esa consulta no esta configurada o
            # falla, para nunca dejar una factura sin razon social.
            spoken_guess = ""
            if _RUC_RE.search(raw_value):
                spoken_guess = _RUC_RE.sub("", raw_value)
                spoken_guess = re.sub(
                    r"\b(el\s+ruc\s+es|ruc|es|y|razon\s+social|la\s+razon\s+social\s+es)\b", "", spoken_guess,
                    flags=re.IGNORECASE,
                ).strip(" ,.-")
            fallback_name = spoken_guess or (state.customer.get("name") if state.customer else None) or "CLIENTE"
            razon_social = await _lookup_document_holder_name("6", ruc, fallback_name)
            state.invoice_document_type = "factura"
            state.factura_ruc = ruc
            state.factura_razon_social = razon_social
            state.pending_ruc_rejection_message = None
            if state.customer and state.customer.get("id"):
                state.customer["doc_type"] = "6"
                state.customer["doc_number"] = ruc
                state.customer["legal_name"] = razon_social
                await CustomerService(self.session, self.tenant_id).update_tax_info(
                    state.customer["id"], "6", ruc, razon_social
                )
                await self.session.commit()
            return

    def _build_summary(self, state: ConversationState) -> str:
        lines = [
            f"{item.quantity} {speakify_product_name(item.name)}" + (f" ({item.notes})" if item.notes else "")
            for item in state.items
        ]
        total = sum(item.quantity * item.unit_price for item in state.items)
        # Cobro del motorizado: siempre visible en el resumen hablado, nunca
        # agregado en silencio -- lo que se dice tiene que ser exactamente
        # lo que despues se cobra. Solo en delivery, nunca en recojo.
        if state.fulfillment_type == "delivery":
            lines.append("1 Delivery")
            total += settings.delivery_fee_soles
        time_part = f" para las {state.requested_time}" if state.requested_time else ""

        if state.fulfillment_type == "delivery":
            place_part = f", delivery a {state.delivery_address}" if state.delivery_address else ", por delivery"
        elif state.fulfillment_type == "pickup":
            place_part = ", recojo en el local"
        else:
            place_part = ""

        payment_part = f", pagas con {state.payment_method}" if state.payment_method else ""
        if state.payment_method == "yape" and state.yape_approval_code:
            payment_part += f", código {state.yape_approval_code}"
        name = state.customer.get("name") if state.customer else None
        name_part = f" A nombre de {name}." if name else ""
        # El nombre/razon social real (via api.apiperu.pe -- ver
        # _lookup_document_holder_name) se lee de vuelta ademas del numero,
        # para que el cliente confirme que es la persona/empresa correcta
        # antes de emitir el comprobante -- pedido explicito: "que me
        # repita mi DNI o mi RUC" debe traer el dato real de apiperu.pe, no
        # solo eco de los digitos.
        document_part = ""
        if state.invoice_document_type == "boleta" and state.boleta_dni:
            document_part = f" Comprobante: boleta con DNI {state.boleta_dni}"
            if state.boleta_dni_name:
                document_part += f", a nombre de {state.boleta_dni_name}"
            document_part += "."
        elif state.invoice_document_type == "factura" and state.factura_ruc:
            document_part = f" Comprobante: factura con RUC {state.factura_ruc}"
            if state.factura_razon_social:
                document_part += f", {state.factura_razon_social}"
            document_part += "."

        return (
            f"Perfecto: {', '.join(lines)}. Son {_format_money_for_voice(total)}{time_part}{place_part}{payment_part}."
            f"{name_part}{document_part} ¿Confirmas?"
        )

    async def _confirm_order(self, state: ConversationState, tool_calls: list[ToolCallOut]) -> OrderOut | None:
        items_context = [
            {"product_id": item.product_id, "quantity": item.quantity, "notes": item.notes}
            for item in state.items
        ]
        if state.fulfillment_type == "delivery":
            # El cobro del motorizado tiene que quedar como un item real del
            # pedido (mismo total que ya se dijo en _build_summary), no solo
            # sumado aparte -- asi aparece igual en el panel de admin y en el
            # WhatsApp de confirmacion. "Delivery" es un producto real del
            # catalogo (ver scripts/ensure_delivery_fee_product.py), no un
            # cargo inventado sin product_id.
            delivery_result = await self._call_tool(tool_calls, "products.search", {"query": "Delivery"})
            delivery_product = next(
                (p for p in delivery_result.get("products", []) if p["name"] == "Delivery"), None
            )
            if delivery_product:
                items_context.append({"product_id": delivery_product["id"], "quantity": 1, "notes": None})
            else:
                logger.warning(
                    "Producto 'Delivery' no encontrado en el catalogo -- pedido confirmado sin cobro de motorizado."
                )

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
            "payment_reference": state.yape_approval_code,
            "channel": "whatsapp",  # canal de la notificacion de confirmacion, no el de la conversacion
            "items": items_context,
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
