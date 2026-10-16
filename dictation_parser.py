"""Parser de la apertura del dictado: "Paciente <nombre>, [fecha <fecha>,]
estudio <contenido>".

Sin LLM, sin dependencias externas (solo biblioteca estandar).
Requiere Python 3.9+ y, en Linux, el paquete 'tzdata' en requirements.txt.

Contrato de seguridad (FALLA CERRADA):
  - result.ok == False  ->  NO llamar al LLM. Pedir confirmacion de nombre
    (y/o fecha) al usuario y recien despues continuar.
  - result.remaining_text es lo UNICO que puede viajar al LLM.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Argentina/Cordoba")

MAX_NAME_WORDS = 8
MAX_DATE_WORDS = 6
STRONG_PUNCT = ",;.:"

NAME_STOPS = {"fecha", "estudio"}
DATE_STOPS = {"estudio"}

# Si aparece una de estas palabras despues del primer token del nombre,
# se asume que empezo el contenido clinico. Ampliable.
MODALITY_WORDS = {
    "tomografia", "resonancia", "ecografia", "radiografia", "mamografia",
    "densitometria", "angiotomografia", "angioresonancia", "ecodoppler",
    "doppler", "eco", "rx", "tc", "rm", "tac", "rmn", "pet",
}

LOWER_PARTICLES = {"de", "del", "la", "las", "los", "y", "da", "di", "van", "von"}

MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
    "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
}


@dataclass
class ParsedDictation:
    ok: bool
    patient_name: Optional[str]
    study_date: date
    date_source: str  # "dictated" | "default"
    remaining_text: Optional[str]
    reasons: List[str] = field(default_factory=list)


def _norm(token: str) -> str:
    """Minusculas, sin tildes ni puntuacion en los bordes."""
    t = unicodedata.normalize("NFKD", token)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.lower().strip(STRONG_PUNCT + "\"'()")


def _ends_strong(token: str) -> bool:
    return token[-1:] in STRONG_PUNCT


def _cap(word: str) -> str:
    """Capitaliza respetando guiones y apostrofes (O'Brien, Perez-Gomez)."""
    return re.sub(
        r"(^|[-'])([^-']+)",
        lambda m: m.group(1) + m.group(2)[:1].upper() + m.group(2)[1:].lower(),
        word,
    )


def format_name(tokens: List[str]) -> str:
    out = []
    for i, tok in enumerate(tokens):
        clean = tok.strip(STRONG_PUNCT + "\"()")
        if i > 0 and _norm(clean) in LOWER_PARTICLES:
            out.append(clean.lower())
        else:
            out.append(_cap(clean))
    return " ".join(out)


def parse_date_text(text: str, today: date) -> Optional[date]:
    """Devuelve la fecha o None si no se puede interpretar con certeza.

    Soporta: hoy, ayer, anteayer / antes de ayer, "14 de octubre",
    "14 de octubre de 2026", "14/10", "14/10/2026", "14-10-26" (dia/mes).
    Sin anio: se asume el actual; si queda en el futuro, el anterior.
    Una fecha futura con anio explicito NO se acepta.
    """
    t = _norm(text)
    t = re.sub(r"\s+", " ", t)
    if t == "hoy":
        return today
    if t == "ayer":
        return today - timedelta(days=1)
    if t in ("anteayer", "antes de ayer"):
        return today - timedelta(days=2)

    day = month = year = None
    m = re.fullmatch(r"(\d{1,2}) de ([a-z]+)(?: de (\d{4}))?", t)
    if m and m.group(2) in MONTHS:
        day, month = int(m.group(1)), MONTHS[m.group(2)]
        year = int(m.group(3)) if m.group(3) else None
    else:
        m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2}|\d{4}))?", t)
        if not m:
            return None
        day, month = int(m.group(1)), int(m.group(2))
        if m.group(3):
            year = int(m.group(3))
            if year < 100:
                year += 2000

    explicit_year = year is not None
    if year is None:
        year = today.year
    try:
        result = date(year, month, day)
    except ValueError:
        return None
    if result > today:
        if explicit_year:
            return None
        try:
            result = date(year - 1, month, day)
        except ValueError:
            return None
    return result


def parse_dictation(text: str, now: Optional[datetime] = None) -> ParsedDictation:
    now = now or datetime.now(TZ)
    today = now.astimezone(TZ).date()
    reasons: List[str] = []

    def fail(why: str, name=None, study=today, src="default") -> ParsedDictation:
        reasons.append(why)
        return ParsedDictation(False, name, study, src, None, reasons)

    tokens = (text or "").split()
    if not tokens or _norm(tokens[0]) != "paciente":
        return fail("falta_palabra_paciente")

    # --- nombre ---
    i = 1
    name_tokens: List[str] = []
    stopped = False
    while i < len(tokens) and len(name_tokens) < MAX_NAME_WORDS:
        tok = tokens[i]
        n = _norm(tok)
        if n in NAME_STOPS or (name_tokens and n in MODALITY_WORDS):
            stopped = True
            break
        name_tokens.append(tok)
        i += 1
        if _ends_strong(tok):
            stopped = True
            break
    if not name_tokens:
        return fail("nombre_vacio")
    if not stopped and i < len(tokens):
        return fail("nombre_demasiado_largo_o_ambiguo")
    name = format_name(name_tokens)

    # --- fecha opcional ---
    study_date, source = today, "default"
    if i < len(tokens) and _norm(tokens[i]) == "fecha":
        i += 1
        date_tokens: List[str] = []
        while i < len(tokens) and len(date_tokens) < MAX_DATE_WORDS:
            tok = tokens[i]
            n = _norm(tok)
            if n in DATE_STOPS or n in MODALITY_WORDS:
                break
            date_tokens.append(tok)
            i += 1
            if _ends_strong(tok):
                break
        parsed = parse_date_text(" ".join(date_tokens), today)
        if parsed is None:
            return fail("fecha_no_interpretable", name=name)
        study_date, source = parsed, "dictated"

    # --- resto ---
    if i < len(tokens) and _norm(tokens[i]) == "estudio":
        i += 1
    remaining = " ".join(tokens[i:]).strip(" ,;:")
    if not remaining:
        return fail("sin_contenido_clinico", name=name, study=study_date, src=source)

    return ParsedDictation(True, name, study_date, source, remaining, reasons)
