"""Utilidades de normalizacion de texto en espanol, usadas por el matching
de productos y por el parser de mensajes del agente (NLU basado en reglas)."""

import re
import unicodedata

# Puntuacion que un ASR (voz->texto de Twilio/Telnyx) o un usuario normal
# agrega sin querer ("No, gracias.", "¿Confirmo?"). OJO: el guion NO esta
# en esta lista a proposito, porque "Coca-Cola" debe seguir siendo un solo
# token para el matching de productos (ver tokenize()).
_PUNCTUATION_RE = re.compile(r"[,.;:!?¡¿\"'()]")


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(text: str) -> str:
    text = strip_accents(text).lower().strip()
    return _PUNCTUATION_RE.sub("", text)


# Orden de mas largo a mas corto -- importa: "papitas" debe calzar con
# "itas" (le saca la "s" de plural de una), no cortarse primero por un
# sufijo mas corto que deje "s" colgando.
_DIMINUTIVE_SUFFIXES = ("citas", "citos", "cita", "cito", "itas", "itos", "ita", "ito")


def _strip_diminutive(word: str) -> str:
    """Diminutivos ("hamburguesita", "papitas", "bebidita", "cafecito") son
    muy comunes en espanol hablado casual, y sin esto no calzaban contra el
    nombre real del producto en el catalogo -- bug real, visto en vivo en
    una llamada telefonica real. Umbral de 6 caracteres antes de intentarlo:
    evita corromper palabras cortas que por casualidad terminan parecido
    (ej. "cita" como sustantivo -- una cita medica -- no diminutivo de nada)."""
    if len(word) < 6:
        return word
    for suffix in _DIMINUTIVE_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def singularize(word: str) -> str:
    diminutive_stripped = _strip_diminutive(word)
    if diminutive_stripped != word:
        # El sufijo diminutivo ya se llevo el plural tambien si aplicaba
        # ("papitas" -> "itas" saca la "s" de una). NO seguir con las
        # reglas de plural de abajo sobre el resultado: "hamburguesita" sin
        # el "ita" queda "hamburgues", que termina en "es" y el chequeo de
        # plural de mas abajo lo recortaba de nuevo a "hamburgu" -- bug real
        # encontrado al probar este mismo fix antes de desplegarlo.
        return diminutive_stripped
    if word.endswith("ces") and len(word) > 4:
        return word[:-3] + "z"
    if word.endswith("es") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and len(word) > 3:
        return word[:-1]
    return word


# Palabras funcionales sin ningun valor para matchear productos/categorias.
# Bug real, visto en vivo: la transcripcion "hamburguesa DE chequera" (STT
# mal entendido) le daba a "Aros de Cebolla" el mismo puntaje que a las
# hamburguesas reales en ProductService.search_scored, porque "de" hacia
# match EXACTO de palabra completa contra el "de" de "Aros DE Cebolla" --
# quedaban empatadas y "Aros de Cebolla" se colaba en una pregunta de
# desambiguacion de hamburguesas. Ningun nombre de producto real depende de
# estas palabras para distinguirse de otro, asi que se descartan siempre.
_STOPWORDS = {
    "de", "del", "la", "el", "lo", "los", "las", "un", "una", "uno", "unos", "unas",
    "y", "o", "con", "sin", "por", "para", "que", "al", "en",
}


def tokenize(text: str) -> list[str]:
    words = [w for w in normalize_text(text).split() if w and w not in _STOPWORDS]
    return [s for w in words if (s := singularize(w)) not in _STOPWORDS]


def tokens_partial_match(a: str, b: str) -> bool:
    """Un token "calza parcialmente" con otro solo si uno es PREFIJO o
    SUFIJO del otro (minimo 3 caracteres) -- nunca si aparece solo en medio.
    Bug real, visto en vivo: "cola" (el cliente pidiendo una gaseosa) es
    substring de "chocolate" ("cho-COLA-te", en medio de la palabra), asi
    que con un chequeo de substring sin restriccion "Volcan de Chocolate"
    (un postre) se colaba como alternativa valida junto a "Coca-Cola" en una
    pregunta de desambiguacion sin ningun sentido. Los casos legitimos de
    match parcial en este proyecto son plurales/diminutivos ya recortados
    por singularize() (siempre quedan como PREFIJO de la palabra completa:
    "hamburgues" de "hamburguesa", "bebid" de "bebida") o una palabra suelta
    que es parte de un nombre compuesto real ("cola" es SUFIJO de
    "coca-cola") -- ningun caso real depende de un match a mitad de
    palabra."""
    if a == b:
        return True
    if len(a) < 3 or len(b) < 3:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return longer.startswith(shorter) or longer.endswith(shorter)
