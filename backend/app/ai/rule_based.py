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

from app.ai.base import ParsedDetailAnswer, ParsedItem, ParsedMessage
from app.domain.text_utils import normalize_text, tokenize

NUMBER_WORDS = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
}
_QTY_ALTERNATION = "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))
QTY_PATTERN = rf"(\d+|{_QTY_ALTERNATION})"

CONFIRM_WORDS = {"si", "sí", "confirmo", "confirmar", "dale", "ok", "okay", "correcto", "perfecto", "asi es"}
CANCEL_WORDS = {"no", "cancela", "cancelar", "olvidalo", "olvídalo", "mejor no"}
HANDOFF_PHRASES = {"hablar con alguien", "hablar con una persona", "hablar con un humano", "asesor humano", "quiero un humano"}
MENU_INQUIRY_PHRASES = {
    "que tienen", "que hay", "hay algo", "el menu", "la carta", "que me recomiendas",
    "tienen algo", "que tienes", "que ofrecen", "opciones hay", "ver el menu",
}
_REMOVE_PREFIXES = ("quita ", "quitar ", "elimina ", "eliminar ", "saca ", "sacar ", "ya no quiero ", "cancela la ", "cancela el ")
_INCREASE_PREFIXES = ("aumenta ", "aumentar ", "agrega mas ", "mas ", "dame mas ", "un poco mas de ")
_DECREASE_PREFIXES = ("disminuye ", "reduce ", "menos ", "un poco menos de ")
_ADD_PREFIXES = (
    "quiero ", "quisiera ", "dame ", "deme ", "pideme ", "pídeme ", "necesito ",
    "quiero pedir ", "quiero ordenar ", "me provoca ", "me provoca pedir ",
    "me falta ", "falta ", "se me olvido ", "se me olvidó ", "tambien quiero ",
    "también quiero ", "agregame ", "agrégame ", "ponme ", "ah ", "ah y ", "y ",
)
_EDIT_PREFIXES = _REMOVE_PREFIXES + _INCREASE_PREFIXES + _DECREASE_PREFIXES
_SET_TO_PATTERN = rf"\b(?:a|en|para que sean|que sean|dejalo en|déjalo en|dejala en|déjala en)\s+{QTY_PATTERN}\b\s*$"
_NOTE_WORD = r"[a-záéíóúñ]+(?:\s+[a-záéíóúñ]+){0,5}"
_SAUCE_WORDS = {
    "aji", "ají", "mayonesa", "mayo", "ketchup", "catsup", "tartara", "tártara",
    "huancaina", "huancaína", "rocoto", "mostaza",
    # OJO: "bbq"/"barbecue" NO van aca a proposito -- colisiona con el
    # producto real "Hamburguesa BBQ". Con "bbq" en esta lista, "quiero una
    # hamburguesa, BBQ" (con pausa) fusionaba "BBQ" como nota de salsa sobre
    # un item que quedaba generico ("hamburguesa"), en vez de dejar que
    # resuelva la variante correcta. Bug real, encontrado por prueba directa.
}
_GREETING_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"hola(?:\s+(?:buenas|buenos\s+d[ií]as|buenas\s+tardes|buenas\s+noches|c[oó]mo\s+est[aá]s|que\s+tal))?"
    r"|buenas(?:\s+tardes|\s+noches)?"
    r"|buenos\s+d[ií]as"
    r"|buen\s+d[ií]a"
    r"|al[oó]"
    r"|qu[eé]\s+tal"
    r")(?:[\s,.;:!?¡¿]+|$)",
    re.IGNORECASE,
)
_SMALLTALK_ONLY_WORDS = {
    "alo", "amigo", "buen", "buena", "buenas", "buenos", "como", "dia", "dias",
    "estas", "esta", "gracias", "hola", "noches", "que", "senor", "senora",
    "tal", "tarde", "tardes", "todo",
}
_SMALLTALK_ONLY_PHRASES = {
    "como estas",
    "gracias",
    "hola como estas",
    "que tal",
    "todo bien",
}
_AUDIO_REPAIR_PHRASES = {
    "esta mudo",
    "esta muda",
    "no me escuchas",
    "no oigo",
    "no responde",
    "no se escucha",
    "no se oye",
    "no te escuche",
    "no te escucho",
    "no te oigo",
    "se corta",
    "se esta cortando",
    "sigue mudo",
    "sigue muda",
}
_PRODUCT_SEQUENCE_PATTERNS = [
    (re.compile(pattern), canonical)
    for pattern, canonical in (
        (r"(?<!\w)hamburguesas?\s+clasicas?(?!\w)", "hamburguesa clasica"),
        (r"(?<!\w)hamburguesas?\s+dobles?(?!\w)", "hamburguesa doble"),
        (r"(?<!\w)hamburguesas?\s+vegetarianas?(?!\w)", "hamburguesa vegetariana"),
        (r"(?<!\w)hamburguesas?\s+bbq(?!\w)", "hamburguesa bbq"),
        (r"(?<!\w)hamburguesas?(?!\w)", "hamburguesa"),
        (r"(?<!\w)(?:inca|inka)\s+(?:kola|cola)s?(?!\w)", "Inca Kola"),
        (r"(?<!\w)(?:indo\s*kola|indocola)s?(?!\w)", "Inca Kola"),
        (r"(?<!\w)coca[-\s]?colas?(?!\w)", "Coca-Cola"),
        (r"(?<!\w)chichas?\s+moradas?(?!\w)", "chicha morada"),
        (r"(?<!\w)limonadas?(?!\w)", "limonada"),
        (r"(?<!\w)aguas?(?:\s+minerales?)?(?!\w)", "agua mineral"),
        (r"(?<!\w)papas?(?:\s+fritas?(?:\s+clasicas?)?)?(?!\w)", "papas fritas"),
        (r"(?<!\w)aros?(?:\s+de\s+cebolla)?(?!\w)", "aros de cebolla"),
        (r"(?<!\w)nuggets?(?:\s+de\s+pollo)?(?!\w)", "nuggets de pollo"),
        (r"(?<!\w)ensaladas?(?!\w)", "ensalada"),
        (r"(?<!\w)alfajores?(?!\w)", "alfajor"),
        (r"(?<!\w)helados?(?:\s+\d+\s+bolas?)?(?!\w)", "helado"),
        (r"(?<!\w)volcan(?:es)?\s+de\s+chocolate(?!\w)", "volcan de chocolate"),
    )
]
_PRODUCT_SEQUENCE_FILLER_WORDS = {
    "ademas", "aparte", "con", "mas", "por", "favor", "porfa", "porfavor",
    "gracias", "obviamente", "tambien", "una", "un", "uno", "y",
    *_QTY_ALTERNATION.split("|"),
}


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
    elif meridiem == "am" and hour == 12:
        # "12 am" es medianoche (00:00), no las 12 del mediodia. Sin este
        # caso quedaba igual que "12 pm" (mismo bug que se arreglo en
        # gemini._normalize_time; aca faltaba el mismo ajuste).
        hour = 0
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
    notes: list[str] = []
    cleaned = text
    patterns = (
        (rf"\bsin\s+({_NOTE_WORD})", "sin"),
        (rf"\bcon\s+({_NOTE_WORD})", "con"),
    )
    for pattern, prefix in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            notes.append(f"{prefix} {value}")
            cleaned = (cleaned[: match.start()] + cleaned[match.end():]).strip()

    return cleaned, "; ".join(notes) if notes else None


def _normalize_prefix(prefix: str) -> str:
    """normalize_text() hace .strip() al final, asi que un prefijo como
    "y " (la palabra completa "y", para frases como "una hamburguesa Y una
    coca cola") perdia su espacio final y quedaba en "y" solo -- eso lo
    convertia en un prefijo de UNA letra que calzaba contra CUALQUIER
    palabra que simplemente empezara con "y" ("Yape", el metodo de pago).
    Bug real, visto en vivo: "Yape, yape." perdia las 2 primeras letras de
    cada "Yape" (len("y ") == 2) y quedaba "pe", que se buscaba como si
    fuera un producto -- ademas de perder el metodo de pago, el camino de
    busqueda de items se disparaba igual sobre un pedido ya armado,
    duplicando cantidades por error. Se reconstruye el espacio final a
    mano para no perder ese limite de palabra."""
    normalized = normalize_text(prefix)
    if prefix.endswith(" ") and not normalized.endswith(" "):
        normalized += " "
    return normalized


def _strip_known_prefix(chunk: str, prefixes: tuple[str, ...]) -> tuple[str, bool]:
    lowered = normalize_text(chunk)
    for prefix in prefixes:
        if lowered.startswith(_normalize_prefix(prefix)):
            return chunk[len(prefix):].strip(), True
    return chunk, False


def _strip_leading_articles(text: str) -> str:
    return re.sub(r"^(el|la|los|las|un|una|unos|unas)\s+", "", text.strip(), flags=re.IGNORECASE)


def _strip_leading_smalltalk(text: str) -> str:
    cleaned = text.strip()
    while cleaned:
        match = _GREETING_PREFIX_RE.match(cleaned)
        if not match:
            break
        cleaned = cleaned[match.end():].strip(" ,.;:!?¡¿")
    return cleaned


def _is_smalltalk_only(text: str) -> bool:
    remainder = _strip_leading_smalltalk(text)
    if not remainder:
        return True
    lowered = normalize_text(remainder)
    if lowered in _SMALLTALK_ONLY_PHRASES:
        return True
    words = set(lowered.split())
    return bool(words) and words <= _SMALLTALK_ONLY_WORDS


def is_audio_repair_message(text: str) -> bool:
    """Frases de llamada rota: no son pedido, aunque traigan "no" o un resto
    raro del ASR. Se expone para que el runtime pueda responder con una
    repregunta util sin cancelar ni buscar productos inexistentes."""
    lowered = normalize_text(_strip_leading_smalltalk(text)).replace("-", " ")
    words = set(lowered.split())
    if not words:
        return False

    if any(phrase in lowered for phrase in _AUDIO_REPAIR_PHRASES):
        return True
    if "mudo" in words or "muda" in words:
        return True
    if "no" in words and any(stem in lowered for stem in ("escuch", "oigo", "oye")):
        return True
    return "corta" in words and ("se" in words or "llamada" in words)


def _looks_like_modifier_phrase(text: str) -> bool:
    lowered = normalize_text(_strip_leading_articles(text))
    tokens = set(lowered.split())
    if not lowered:
        return False
    if "en vez de" in lowered or "aparte" in lowered:
        return True
    if tokens & _SAUCE_WORDS:
        return True
    return lowered.startswith(("crema ", "cremas ", "salsa ", "salsas "))


def _append_note(item: ParsedItem, note: str) -> None:
    item.notes = f"{item.notes}; {note}" if item.notes else note


def _known_product_matches(text: str) -> list[tuple[int, int, str]]:
    normalized = normalize_text(text)
    raw_matches: list[tuple[int, int, str]] = []
    for pattern, canonical in _PRODUCT_SEQUENCE_PATTERNS:
        raw_matches.extend((match.start(), match.end(), canonical) for match in pattern.finditer(normalized))

    selected: list[tuple[int, int, str]] = []
    occupied_until = -1
    for start, end, canonical in sorted(raw_matches, key=lambda row: (row[0], -(row[1] - row[0]))):
        if start < occupied_until:
            continue
        selected.append((start, end, canonical))
        occupied_until = end
    return selected


def _gap_is_only_product_sequence_filler(gap: str) -> bool:
    words = [word for word in normalize_text(gap).split() if word]
    return all(word in _PRODUCT_SEQUENCE_FILLER_WORDS or word in NUMBER_WORDS for word in words)


def _split_known_product_sequence(text: str) -> list[str] | None:
    matches = _known_product_matches(text)
    if len(matches) < 2:
        return None

    normalized = normalize_text(text)
    gaps = [normalized[: matches[0][0]], normalized[matches[-1][1]:]]
    gaps.extend(normalized[matches[index][1]: matches[index + 1][0]] for index in range(len(matches) - 1))
    if not all(_gap_is_only_product_sequence_filler(gap) for gap in gaps):
        return None

    return [canonical for _, _, canonical in matches]


def _parse_items(text: str) -> list[ParsedItem]:
    # Descarta relleno antes del primer producto ("Hola, quiero...") para que
    # la cantidad no quede pegada a palabras como "quiero"/"hola".
    lead_match = re.search(rf"\b{QTY_PATTERN}\b", text, re.IGNORECASE)
    prefix_before_qty = normalize_text(text[: lead_match.start()]) if lead_match else ""
    if lead_match and not any(normalize_text(prefix).strip() in prefix_before_qty for prefix in _EDIT_PREFIXES):
        text = text[lead_match.start():]

    items: list[ParsedItem] = []
    for chunk in _split_chunks(text):
        chunk_lower = normalize_text(chunk)
        action = "add"
        for prefix in _REMOVE_PREFIXES:
            if chunk_lower.startswith(prefix):
                action = "remove"
                chunk = chunk[len(prefix):]
                break
        else:
            for prefix in _INCREASE_PREFIXES:
                if chunk_lower.startswith(prefix):
                    action = "increase"
                    chunk = chunk[len(prefix):]
                    break
            else:
                for prefix in _DECREASE_PREFIXES:
                    if chunk_lower.startswith(prefix):
                        action = "decrease"
                        chunk = chunk[len(prefix):]
                        break
                else:
                    chunk, _ = _strip_known_prefix(chunk, _ADD_PREFIXES)

        chunk = chunk.strip()

        qty_match = re.match(rf"^{QTY_PATTERN}\b\s*(.*)$", chunk, re.IGNORECASE)
        if qty_match:
            quantity = _parse_quantity(qty_match.group(1)) or 1
            rest = qty_match.group(2).strip()
        else:
            quantity = 1
            rest = chunk.strip()

        if action in {"increase", "decrease"}:
            set_match = re.search(_SET_TO_PATTERN, rest, re.IGNORECASE)
            if set_match:
                set_qty_match = re.search(QTY_PATTERN, set_match.group(0), re.IGNORECASE)
                quantity = _parse_quantity(set_qty_match.group(1)) if set_qty_match else quantity
                quantity = quantity or 1
                rest = rest[: set_match.start()].strip()
                action = "set"

        sequence_parts = _split_known_product_sequence(rest)
        if sequence_parts:
            for index, query in enumerate(sequence_parts):
                items.append(
                    ParsedItem(
                        raw_text=query,
                        quantity=quantity if index == 0 else 1,
                        query=query,
                        action=action,
                    )
                )
            continue

        rest, note = _extract_note(rest)
        rest = _strip_leading_articles(rest)
        if rest and not re.search(r"[0-9a-záéíóúñ]", rest, re.IGNORECASE):
            continue
        if rest and not tokenize(rest):
            continue
        if rest and _gap_is_only_product_sequence_filler(rest):
            # Bug real, visto en vivo: "¿Me da una hamburguesa vegetariana,
            # por favor?" -- al separar por comas, la clausula "por favor"
            # quedaba como su propio chunk. No tiene ningun 0-2 caracteres
            # raros (pasaba el chequeo de arriba) y "favor" sobrevive a
            # tokenize() (no es un stopword), asi que se buscaba como
            # producto -- perdiendo ademas el item real que si se dijo en
            # el mismo mensaje. Relleno puro ("por favor", "porfa",
            # "gracias"...) nunca es un producto.
            continue

        if not rest and note and items:
            # Modificador suelto ("una sin cebolla"): se pega al item anterior
            # en vez de crear un producto nuevo, porque no trae sustantivo.
            previous = items[-1]
            extra = f"{note} (x{quantity})" if quantity != previous.quantity else note
            _append_note(previous, extra)
            continue

        if action == "add" and rest and _looks_like_modifier_phrase(rest) and items:
            previous = items[-1]
            extra = rest if note is None else f"{rest}; {note}"
            _append_note(previous, extra)
            continue

        if not rest:
            continue

        items.append(ParsedItem(raw_text=chunk, quantity=quantity, query=rest, notes=note, action=action))
    return items


def _is_menu_inquiry(lowered: str) -> bool:
    if any(phrase in lowered for phrase in MENU_INQUIRY_PHRASES):
        return True
    # Bug real, visto en vivo: "¿Tiene parrilla?" (forma "usted", muy comun
    # al hablar con un restaurante) no calzaba -- solo estaban cubiertas
    # "tienen"/"tienes". Sin esto, "parrilla" se trataba como un producto
    # ambiguo a medio pedir y la respuesta salia rota ("¿Cual ¿Tiene
    # parrilla? prefieres...").
    question_starters = ("que ", "cuales ", "cuáles ", "hay ", "tiene ", "tienen ", "tienes ")
    inquiry_terms = (
        "tiene", "tienen", "tienes", "hay", "ofrecen", "menu", "menú", "carta", "opciones",
        "crema", "cremas", "salsa", "salsas", "bebida", "bebidas", "hamburguesa",
        "hamburguesas", "postre", "postres", "parrilla", "parrillas", "pollo",
        "pastas", "chaufa", "chaufas",
    )
    return lowered.startswith(question_starters) and any(term in lowered for term in inquiry_terms)


_CLAUSE_SPLIT_RE = re.compile(r"[,.?!]+")


def _split_off_order_after_menu_question(text: str) -> str | None:
    """Bug real: "Que bebidas tienen? Deme dos Coca-Colas" se detectaba
    entero como menu.inquiry (la pregunta domina el mensaje completo) y el
    pedido quedaba mudo -- el cliente pagaba el silencio del agente, no la
    Coca-Cola. Si el mensaje tiene varias clausulas y no TODAS son preguntas
    de menu, separamos las que si lo son y probamos si el resto es un
    pedido real. Solo lo aceptamos si esa clausula trae una señal de pedido
    concreta (cantidad, o un prefijo de accion conocido) para no inventar
    un item de un resto de frase que no es ni pregunta ni pedido."""
    clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]
    if len(clauses) <= 1:
        return None
    kept = [c for c in clauses if not _is_menu_inquiry(normalize_text(c))]
    if not kept or len(kept) == len(clauses):
        return None
    order_text = ", ".join(kept)
    has_quantity = re.search(QTY_PATTERN, order_text, re.IGNORECASE)
    has_action_prefix = any(
        normalize_text(order_text).startswith(_normalize_prefix(prefix))
        for prefix in _ADD_PREFIXES + _EDIT_PREFIXES
    )
    if not has_quantity and not has_action_prefix:
        return None
    return order_text


class RuleBasedProvider:
    name = "rule_based"

    async def parse_message(
        self,
        message: str,
        *,
        awaiting_confirmation: bool,
        pending_detail: str | None = None,
    ) -> ParsedMessage:
        text = message.strip()
        lowered = normalize_text(text)

        if is_audio_repair_message(text):
            return ParsedMessage(intent="smalltalk")

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

        if _is_smalltalk_only(text):
            return ParsedMessage(intent="smalltalk")

        text = _strip_leading_smalltalk(text)
        lowered = normalize_text(text)

        if _is_menu_inquiry(lowered):
            order_text = _split_off_order_after_menu_question(text)
            if order_text:
                order_items_text, order_time = _extract_time(order_text)
                trailing_items = _parse_items(order_items_text)
                if trailing_items:
                    return ParsedMessage(intent="order.create", items=trailing_items, requested_time=order_time)
            return ParsedMessage(intent="menu.inquiry")

        items_text, requested_time = _extract_time(text)
        items = _parse_items(items_text)
        if items:
            return ParsedMessage(intent="order.create", items=items, requested_time=requested_time)

        if pending_detail:
            detail_value = _parse_detail_answer(text, lowered, pending_detail)
            if detail_value:
                return ParsedMessage(
                    intent="detail.answer",
                    detail_answer=ParsedDetailAnswer(True, detail_value),
                )

        return ParsedMessage(intent="smalltalk")


def _parse_detail_answer(text: str, lowered: str, pending_detail: str) -> str | None:
    if pending_detail == "fulfillment":
        if any(k in lowered for k in ("delivery", "envio", "envío", "domicilio", "llevar", "llevas")):
            return "delivery"
        if any(k in lowered for k in ("recog", "recojo", "pasar", "tienda", "local", "voy yo", "paso yo")):
            return "pickup"
        return None

    if pending_detail == "payment":
        if "yape" in lowered:
            return "yape"
        if "plin" in lowered:
            return "plin"
        if any(k in lowered for k in ("efectivo", "cash", "contado")):
            return "efectivo"
        if "tarjeta" in lowered:
            return "tarjeta"
        return None

    cleaned = text.strip(" .")
    suspicious = (
        "quiero", "dame", "falta", "agrega", "quita", "cambia", "menu", "menú",
        "bebida", "hamburguesa", "papas", "postre", "precio", "cuanto",
    )
    if any(word in lowered for word in suspicious):
        return None

    if pending_detail == "name":
        cleaned = re.sub(
            r"^(mi\s+nombre\s+es|me\s+llamo|soy|es|a\s+nombre\s+de)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip(" .")
        tokens = cleaned.split()
        if 1 <= len(tokens) <= 4 and not re.search(r"\d", cleaned):
            return cleaned
        return None

    if pending_detail == "address":
        cleaned = re.sub(
            r"^(mi\s+direcci[oó]n\s+es|vivo\s+en|es\s+en|en)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip(" .")
        if len(cleaned.split()) >= 2 or re.search(r"\d", cleaned):
            return cleaned
        return None

    return None
