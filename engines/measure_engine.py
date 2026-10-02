"""
measure_engine.py

Redacción de las medidas de un hallazgo, en un solo lugar. Antes esta lógica
estaba duplicada en line_based_report_engine.py y devil_advocate_engine.py;
ahora los dos la importan de acá, así un cambio se hace una sola vez.

Reglas (definidas por Guille):
- La medida se agrega como ", midiendo X" (gerundio: no cambia en plural,
  así que sirve igual para "la pared" y "las paredes").
- Hallazgo sobre la PARED (pared, paredes, parietal, mural): se dice el
  espesor. Órgano hueco -> "de espesor parietal"; vasos (arteria, aorta,
  vena) -> "de espesor mural"; otro -> "de espesor".
- Apéndice engrosado o aumentado de tamaño (el órgano, no su pared): se mide
  el diámetro transverso.
- Si el dictado ya trae la medida pegada al final de la descripción
  ("...apéndice cecal con 11 mm"), se la saca de ahí y se vuelve a redactar
  con las reglas de arriba (strip_trailing_measure).
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


def plain_words(text: Optional[str]) -> list:
    plain = (text or "").lower().translate(str.maketrans("áéíóú", "aeiou"))
    return re.findall(r"[a-zñ]+", plain)


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

    return f", midiendo {size_str}{suffix}"


def ask_measure(text: Optional[str]) -> str:
    """Pregunta del abogado del diablo cuando falta la medida."""
    if any(w in WALL_WORDS for w in plain_words(text)):
        return "¿Cuánto mide el espesor de la pared?"
    return "¿Tenés la dimensión?"
