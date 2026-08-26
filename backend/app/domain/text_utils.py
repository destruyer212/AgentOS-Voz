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


def singularize(word: str) -> str:
    if word.endswith("ces") and len(word) > 4:
        return word[:-3] + "z"
    if word.endswith("es") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and len(word) > 3:
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    return [singularize(w) for w in normalize_text(text).split() if w]
