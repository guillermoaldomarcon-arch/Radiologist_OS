"""
measure_engine.py

Redacción de las medidas de un hallazgo, en un solo lugar. Antes esta lógica
estaba duplicada en line_based_report_engine.py y devil_advocate_engine.py;
ahora los dos la importan de acá, así un cambio se hace una sola vez.

Reglas (definidas por Guille):
- Siempre "que mide X" / "que miden X" (plural si el texto habla de "las
  paredes" o arranca con un sustantivo plural: quistes, nódulos, masas...).
- Hallazgo sobre la PARED (pared, paredes, parietal, mural): se dice el
  espesor. Órgano hueco -> "de espesor parietal"; vasos (arteria, aorta,
  vena) -> "de espesor mural"; otro -> "de espesor".
- Apéndice engrosado o aumentado de tamaño (el órgano, no su pared): se mide
  el diámetro transverso.
"""

import re
from typing import Optional

PLURAL_HEADS = {
    "masas", "quistes", "nodulos", "polipos", "calculos", "abscesos", "tumores",
    "imagenes", "litos", "placas", "diverticulos", "ganglios", "hematomas",
    "lesiones", "calcificaciones", "adenopatias", "pliegues",
}

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


def plain_words(text: Optional[str]) -> list:
    plain = (text or "").lower().translate(str.maketrans("áéíóú", "aeiou"))
    return re.findall(r"[a-zñ]+", plain)


def measure_clause(text: str, size_str: str, organ: Optional[str] = None) -> str:
    """Cláusula de medida para agregar al final de la descripción de un hallazgo."""
    words = plain_words(text)
    organ_words = plain_words(organ)

    plural = "paredes" in words or (bool(words) and words[0] in PLURAL_HEADS)
    verb = "miden" if plural else "mide"

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

    return f", que {verb} {size_str}{suffix}"


def ask_measure(text: Optional[str]) -> str:
    """Pregunta del abogado del diablo cuando falta la medida."""
    if any(w in WALL_WORDS for w in plain_words(text)):
        return "¿Cuánto mide el espesor de la pared?"
    return "¿Tenés la dimensión?"
