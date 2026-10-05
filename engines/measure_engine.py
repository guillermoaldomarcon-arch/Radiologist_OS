"""
measure_engine.py

Redacción de las medidas de un hallazgo, en un solo lugar. Antes esta lógica
estaba duplicada en line_based_report_engine.py y devil_advocate_engine.py;
ahora los dos la importan de acá, así un cambio se hace una sola vez.

Reglas (definidas por Guille):
- Si el hallazgo queda como objeto de "presenta" ("Riñón derecho presenta masa
  renal"), la medida es de la masa: "que mide X" ("que miden" en plural).
- Si el órgano ya está en el texto o el hallazgo es un adjetivo/participio
  ("Apéndice engrosado"), la medida es del órgano o la estructura que se
  describe: ", midiendo X".
- Hallazgo sobre la PARED (pared, paredes, parietal, mural): se dice el
  espesor. Órgano hueco -> "de espesor parietal"; vasos (arteria, aorta,
  vena) -> "de espesor mural"; otro -> "de espesor".
- Apéndice engrosado o aumentado de tamaño (el órgano, no su pared): se mide
  el diámetro transverso.
- Si el dictado ya trae la medida pegada al final de la descripción
  ("...apéndice cecal con 11 mm"), se la saca de ahí y se vuelve a redactar
  con las reglas de arriba (strip_trailing_measure).
- Entre una medida (o un hallazgo) y sus atributos ("márgenes nítidos y
  redondeados") va "con", no una coma (connect_attributes).
"""

import re
from typing import Optional

WALL_WORDS = {"pared", "paredes", "parietal", "parietales", "mural", "murales"}

# Órganos huecos -> "espesor parietal"
HOLLOW_WORDS = {
    "apendice", "vesicula", "biliar", "coledoco", "estomago", "esofago",
    "duodeno", "yeyuno", "ileon", "intestino", "colon", "recto", "sigma",
    "vejiga", "ureter", "uretra",
}

# Vasos -> "espesor mural" (tiene prioridad sobre HOLLOW_WORDS)
MURAL_WORDS = {"aorta", "arteria", "vena", "vaso"}

# Órgano -> medida que se informa cuando el hallazgo es del órgano mismo
# (no de su pared). Se amplía a medida que se definan más estructuras.
DIAMETER_TERMS = {"apendice": "diámetro transverso"}
DIAMETER_TRIGGERS = {
    "engrosado", "engrosada", "engrosamiento", "aumentado", "aumentada",
    "aumento", "dilatado", "dilatada", "dilatacion",
}

# Sustantivos que, al anteponer el órgano, llevan "presenta": "Riñón derecho
# presenta masa renal". Participios y adjetivos no (quedan "Riñón disminuido").
LINK_VERB_NOUNS = {
    "masa", "masas", "quiste", "quistes", "nodulo", "nodulos", "polipo", "polipos",
    "calculo", "calculos", "absceso", "abscesos", "tumor", "tumores", "imagen",
    "imagenes", "liquido", "barro", "lito", "litos", "trombo", "placa", "placas",
    "diverticulo", "diverticulos", "ganglio", "ganglios", "aneurisma", "edema",
    "hematoma", "hematomas", "aumento", "aumentos",
}
LINK_VERB_SUFFIXES = (
    "cion", "ciones", "sion", "siones", "miento", "mientos", "dad", "dades",
    "ia", "itis", "osis", "iasis", "oma", "omas",
)

PLURAL_HEADS = {
    "masas", "quistes", "nodulos", "polipos", "calculos", "abscesos", "tumores",
    "imagenes", "litos", "placas", "diverticulos", "ganglios", "hematomas",
    "lesiones", "calcificaciones", "adenopatias", "pliegues",
}

_ORGAN_STOPWORDS = {"region", "espacio", "area", "zona", "de", "del", "la", "el"}

# Atributos que se describen con "con": "quiste de 20 mm con márgenes nítidos".
_ATTRIBUTE_WORDS = (
    "márgenes|margenes|bordes|contornos|ecoestructura|ecogenicidad|contenido|"
    "halo|refuerzo|sombra|septos|tabiques|calcificaciones|vascularización|"
    "vascularizacion"
)
_MEASURE_THEN_ATTRIBUTE_RE = re.compile(
    rf"(\d(?:[.,]\d+)?\s*(?:mm|cm))\s*,?\s+(?=(?:{_ATTRIBUTE_WORDS})\b)",
    re.IGNORECASE,
)
_COMMA_THEN_ATTRIBUTE_RE = re.compile(
    rf"\s*,\s*(?=(?:{_ATTRIBUTE_WORDS})\b)", re.IGNORECASE
)

# Medida pegada al FINAL de la descripción, con un conector simple:
# "... cecal con 11 mm", "... de 11 mm", "..., 11 mm", "..., midiendo 11 mm".
# No matchea "de aproximadamente 11 mm", "de hasta 11 mm" ni "90 x 120 x 150 mm":
# en esos casos se deja el texto tal cual para no perder información.
_TRAILING_MEASURE_RE = re.compile(
    r"(?:[,;]\s*(?:(?:con|de|midiendo|que\s+mide|que\s+miden|mide|miden)\s+)?"
    r"|\s+(?:con|de|midiendo|que\s+mide|que\s+miden|mide|miden)\s+)"
    r"(\d+(?:[.,]\d+)?)\s*(mm|cm)\s*$",
    re.IGNORECASE,
)


# Concordancia de género del lado: "mama derecha", "glándula suprarrenal
# izquierda", pero "riñón derecho". Se decide por el primer sustantivo del
# nombre del órgano: femenino si termina en "a" o está en esta lista.
FEMININE_HEADS = {"mano", "region", "ingle", "pelvis", "cabeza", "mama", "axila"}
MASCULINE_A_HEADS = {"linfoma", "hematoma", "adenoma", "melanoma", "sistema", "diafragma"}

def plain_words(text: Optional[str]) -> list:
    plain = (text or "").lower().translate(str.maketrans("áéíóú", "aeiou"))
    return re.findall(r"[a-zñ]+", plain)


def organ_in_text(organ: Optional[str], text: Optional[str]) -> bool:
    """¿El texto ya nombra al órgano (o una palabra significativa de su nombre)?"""
    if not organ:
        return False
    text_norm = " ".join(plain_words(text))
    organ_words = plain_words(organ)
    if " ".join(organ_words) and " ".join(organ_words) in text_norm:
        return True
    meaningful = [w for w in organ_words if w not in _ORGAN_STOPWORDS and len(w) > 3]
    return any(w in text_norm for w in meaningful)


def link_verb(text: str, organ: Optional[str], organ_present: bool) -> str:
    """
    " presenta" / " presentan" cuando hay que anteponer el órgano y el hallazgo
    arranca con un sustantivo ("Riñón derecho masa sólida" queda telegráfico).
    Vacío con participios, adjetivos o preposiciones ("disminuido de tamaño",
    "con masa..."), donde agregar el verbo sonaría mal.
    """
    if not organ or organ_present:
        return ""
    words = plain_words(text)
    first = words[0] if words else ""
    if not first:
        return ""
    if first not in LINK_VERB_NOUNS and not first.endswith(LINK_VERB_SUFFIXES):
        return ""
    last = plain_words(organ)[-1] if plain_words(organ) else ""
    plural = last.endswith(("es", "os", "as")) and last not in ("pancreas", "tiroides")
    return " presentan" if plural else " presenta"


def agree_side(organ: Optional[str], side_label: Optional[str]) -> Optional[str]:
    """derecho/izquierdo -> derecha/izquierda si el órgano es femenino."""
    if not side_label or side_label not in ("derecho", "izquierdo"):
        return side_label
    words = plain_words(organ)
    head = words[0] if words else ""
    feminine = head in FEMININE_HEADS or (head.endswith("a") and head not in MASCULINE_A_HEADS)
    if feminine:
        return side_label[:-1] + "a"
    return side_label


def connect_attributes(text: str) -> str:
    """Cambia la coma (o el vacío) antes de márgenes, bordes, etc. por 'con'."""
    if not text:
        return text
    text = _MEASURE_THEN_ATTRIBUTE_RE.sub(r"\1 con ", text)
    return _COMMA_THEN_ATTRIBUTE_RE.sub(" con ", text)


def strip_trailing_measure(text: str, size_mm) -> str:
    """
    Si la descripción termina con una medida igual a size_mm, la saca para que
    measure_clause la vuelva a redactar ("de espesor", "midiendo"...). Solo
    actúa si el número coincide con size_mm; si no, devuelve el texto igual.
    """
    if not text or size_mm is None:
        return text
    match = _TRAILING_MEASURE_RE.search(text)
    if not match:
        return text
    try:
        value = float(match.group(1).replace(",", "."))
        if match.group(2).lower() == "cm":
            value *= 10.0
        if abs(value - float(size_mm)) > 0.05:
            return text
    except (TypeError, ValueError):
        return text
    return text[: match.start()].rstrip(" ,;")


def prepare_description(text: str, size_mm) -> str:
    """Limpia la descripción antes de redactar: 'con' en los atributos y sin medida repetida."""
    return strip_trailing_measure(connect_attributes(text), size_mm)

def with_side(text: str, side: Optional[str]) -> str:
    """Agrega el lado al final si el texto no lo dice ya: '..., del lado derecho'."""
    key = {
        "derecho": "derecho", "derecha": "derecho",
        "izquierdo": "izquierdo", "izquierda": "izquierdo", "bilateral": "bilateral",
    }.get((side or "").strip().lower())
    if not key or not text:
        return text
    if any(w.startswith(("derech", "izquierd", "bilateral", "ambos", "ambas")) for w in plain_words(text)):
        return text
    return f"{text}, bilateral" if key == "bilateral" else f"{text}, del lado {key}"


def _starts_with_finding_noun(text: str) -> bool:
    """¿La descripción arranca con el sustantivo del hallazgo (masa, nódulo, engrosamiento...)?"""
    words = plain_words(text)
    first = words[0] if words else ""
    return bool(first) and (first in LINK_VERB_NOUNS or first.endswith(LINK_VERB_SUFFIXES))


def measure_clause(text: str, size_str: str, organ: Optional[str] = None) -> str:
    """Cláusula de medida para agregar al final de la descripción de un hallazgo."""
    words = plain_words(text)
    organ_words = plain_words(organ)

    suffix = ""
    if any(w in WALL_WORDS for w in words):
        if "espesor" not in words:
            if any(w in MURAL_WORDS for w in organ_words):
                suffix = " de espesor mural"
            elif any(w in HOLLOW_WORDS for w in organ_words):
                suffix = " de espesor parietal"
            else:
                suffix = " de espesor"
    elif "diametro" not in words and any(w in DIAMETER_TRIGGERS for w in words):
        for organ_key, term in DIAMETER_TERMS.items():
            if organ_key in organ_words:
                suffix = f" de {term}"
                break

    # "Riñón derecho presenta masa renal que mide 40 mm": la medida es de la masa.
    if _starts_with_finding_noun(text):
        plural = "paredes" in words or (bool(words) and words[0] in PLURAL_HEADS)
        verb = "miden" if plural else "mide"
        return f" que {verb} {size_str}{suffix}"

    # "Apéndice engrosado, midiendo 11 mm...": la medida es del órgano mismo.
    return f", midiendo {size_str}{suffix}"


def ask_measure(text: Optional[str]) -> str:
    """Pregunta del abogado del diablo cuando falta la medida."""
    if any(w in WALL_WORDS for w in plain_words(text)):
        return "¿Cuánto mide el espesor de la pared?"
    return "¿Tenés la dimensión?"
