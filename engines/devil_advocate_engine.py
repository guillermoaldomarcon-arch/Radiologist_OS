"""
devil_advocate_engine.py

Raises questions about a report's Finding objects before the
radiologist signs -- never modifies anything, only informs.
"""

from __future__ import annotations
import re
from typing import Callable, List, Optional

from finding import Finding
import measure_engine

_ACCENT_MAP = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")


def _strip_accents(text: str) -> str:
    return text.translate(_ACCENT_MAP)

_ORGAN_STOPWORDS = {"region", "espacio", "area", "zona", "de", "del", "la", "el"}


def _organ_meaningfully_present(organ: str, desc_no_accents: str) -> bool:
    """
    Ademas del chequeo de substring exacto, considera presente el organ
    si cualquiera de sus palabras significativas (descartando genericas
    como "region"/"espacio") ya aparece en la descripcion -- cubre el
    caso donde la IA extrae un organ compuesto ("Region subhepatica")
    pero la ubicacion ya esta embebida como adjetivo en desc ("masa...
    subhepatica...").
    """
    organ_words = _strip_accents(organ.lower()).split()
    meaningful = [w for w in organ_words if w not in _ORGAN_STOPWORDS and len(w) > 3]
    return any(w in desc_no_accents for w in meaningful)


_MANAGEMENT_PATTERNS = [
    r"se recomienda\s+(control|seguimiento|repetir|evaluar|biopsia|derivar)",
    r"sugerir\w*\s+(control|seguimiento|biopsia|evaluar)",
    r"control\s+en\s+\d+\s*(mes|año|semana)",
    r"seguimiento\s+a\s+\d+\s*(mes|año|semana)",
    r"correlacionar\s+con\s+(cl[ií]nica|laboratorio)\s+y\s+(tratar|actuar)",
    r"deriva\w*\s+a\s+(especialista|cirug[ií]a|urgencias)",
]
_MANAGEMENT_RE = re.compile("|".join(_MANAGEMENT_PATTERNS), re.IGNORECASE)

_MEASUREMENT_IN_TEXT_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(mm|cm)\b", re.IGNORECASE)


def contains_management_language(text: str) -> bool:
    return bool(_MANAGEMENT_RE.search(text or ""))


def strip_to_classification_only(text: str) -> str:
    match = _MANAGEMENT_RE.search(text or "")
    return text[: match.start()].strip().rstrip(",.;") if match else text


class DevilQuestion:
    def __init__(
        self,
        finding: Optional[Finding],
        question: str,
        reason: str,
        rule_type: str,
        severity: str = "ADVISORY",
        missing_fields: Optional[dict] = None,
        closure_candidates: Optional[dict] = None,
    ):
        self.finding = finding
        self.question = question
        self.reason = reason
        self.rule_type = rule_type
        self.severity = severity
        self.missing_fields = missing_fields or {}
        self.closure_candidates = closure_candidates or {}

    def __repr__(self) -> str:
        target = self.finding.name if self.finding else "(report-level)"
        return f"DevilQuestion(finding={target!r}, rule={self.rule_type}, severity={self.severity!r})"


def _short(text: Optional[str], limit: int = 60) -> str:
    """Recorta a `limit` caracteres sin cortar palabras. Solo para mostrar."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return cut.rstrip(",.;:") + "…"

_SIDE_WORD_RE = re.compile(r"\b(derech[oa]s?|izquierd[oa]s?|bilateral(?:es)?|ambos|ambas)\b")


def check_missing_laterality(findings: List[Finding]) -> List[DevilQuestion]:
    """
    Regla G: estructura par (el extractor marca paired=True) sin lado
    informado ni mencionado en el texto. La respuesta vuelve como
    [LATERALIDAD_CONFIRMADA: ...] y completa el hallazgo existente.
    """
    out = []
    for f in findings:
        if f.status != "ACTIVE" or not getattr(f, "paired", None) or f.side:
            continue
        text = _strip_accents(f"{f.description or ''} {f.location or ''}".lower())
        if _SIDE_WORD_RE.search(text):
            continue
        label = _short(f.description) or f.name
        out.append(DevilQuestion(
            finding=f,
            question=f"¿De qué lado está '{label}'?",
            reason="Estructura par sin lateralidad.",
            rule_type="G",
            closure_candidates={"derecho": "derecho", "izquierdo": "izquierdo", "bilateral": "bilateral"},
        ))
    return out


def check_missing_measurement(findings: List[Finding]) -> List[DevilQuestion]:
    out = []
    for f in findings:
        if f.status == "ACTIVE" and f.size_mm is None:
            desc = _short(f.description)
            name_in_desc = _strip_accents((f.name or "").lower()) in _strip_accents(desc.lower())
            label = f"{f.name}: {desc}" if (desc and not name_in_desc) else (desc or f.name)
            out.append(DevilQuestion(
                finding=f,
                question=f"Mencionaste '{label}' sin medida. {measure_engine.ask_measure(f.description)}",
                reason="Finding ACTIVE sin size_mm.",
                rule_type="B",
            ))
    return out


MODALITY_TERM_CONFLICTS = {
    "RM": {
        "hipodenso": "hipointenso", "hipodensa": "hipointensa",
        "hiperdenso": "hiperintenso", "hiperdensa": "hiperintensa",
        "densidad": "intensidad de señal",
    },
    "TC": {
        "hipointenso": "hipodenso", "hipointensa": "hipodensa",
        "hiperintenso": "hiperdenso", "hiperintensa": "hiperdensa",
    },
}


def check_terminology(findings: List[Finding], modality: str) -> List[DevilQuestion]:
    conflicts = MODALITY_TERM_CONFLICTS.get(modality.upper(), {})
    if not conflicts:
        return []

    out = []
    for f in findings:
        if not f.description:
            continue
        desc_lower = f.description.lower()
        for wrong, correct in conflicts.items():
            if re.search(rf"\b{wrong}\b", desc_lower):
                out.append(DevilQuestion(
                    finding=f,
                    question=f"Dijiste \"{wrong}\" en un estudio de {modality}. "
                              f"¿Quisiste decir \"{correct}\"?",
                    reason=f"Término estándar para {modality}. Sin validar aún "
                            f"contra caso real de RM.",
                    rule_type="C",
                ))
    return out


def extract_margin(text: str) -> Optional[str]:
    t = text.lower()
    if "poco circunscript" in t or "indistint" in t:
        return "indistintos"
    if "espiculad" in t:
        return "espiculados"
    if "microlobulad" in t:
        return "microlobulados"
    if "lobulad" in t or "irregular" in re.sub(r"forma\s+irregular\w*", " ", t):
        return "lobulados/irregulares"
    if "extratiroide" in t:
        return "extension extratiroidea"
    if "circunscript" in t or " liso" in t:
        return "circunscriptos/lisos"
    return None


def extract_shape(text: str) -> Optional[str]:
    t = text.lower()
    if re.search(r"m[aá]s alt[oa] que anch[oa]", t):
        return "mas alto que ancho"
    if "forma irregular" in t:
        return "irregular"
    if "oval" in t or "redond" in t:
        return "ancho/ovalado"
    return None


def extract_composition(text: str) -> Optional[str]:
    t = text.lower()
    if "espongiforme" in t:
        return "espongiforme"
    if "mixta" in t or "mixto" in t:
        return "mixta"
    if "solid" in t:
        return "solida"
    if "quistic" in t:
        return "quistica"
    return None


def extract_echogenic_foci(text: str) -> Optional[str]:
    t = text.lower()
    if "puntiforme" in t or "microcalcificacion" in t:
        return "focos puntiformes"
    if "periferic" in t and "calcificacion" in t:
        return "calcificaciones perifericas"
    if "macrocalcificacion" in t:
        return "macrocalcificaciones"
    if "sin calcificaciones" in t:
        return "ninguno"
    return None


def extract_echogenicity(text: str) -> Optional[str]:
    t = text.lower()
    if "muy hipoecog" in t:
        return "muy hipoecogenico"
    if "hipoecog" in t:
        return "hipoecogenico"
    if "hiperecog" in t:
        return "hiperecogenico"
    if "isoecog" in t:
        return "isoecogenico"
    if "anecoic" in t:
        return "anecoico"
    return None


def classify_birads(margins: Optional[str], shape: Optional[str]) -> Optional[str]:
    if margins is None:
        return None
    if "espiculad" in margins:
        return "BIRADS 5"
    if "indistint" in margins or "microlobulad" in margins:
        return "BIRADS 4"
    if "circunscript" in margins and shape and "oval" in shape:
        return "BIRADS 3"
    return None


def classify_tirads(composition, echogenicity, shape, margin, echogenic_foci) -> Optional[str]:
    fields = [composition, echogenicity, shape, margin, echogenic_foci]
    if any(v is None for v in fields):
        return None
    points = 0
    points += {"quistica": 0, "espongiforme": 0, "mixta": 1, "solida": 2}.get(composition, 0)
    points += {"anecoico": 0, "hiperecogenico": 1, "isoecogenico": 1,
               "hipoecogenico": 2, "muy hipoecogenico": 3}.get(echogenicity, 0)
    points += 3 if shape == "mas alto que ancho" else 0
    points += {"circunscriptos/lisos": 0, "indistintos": 0, "lobulados/irregulares": 2,
               "microlobulados": 2, "extension extratiroidea": 3}.get(margin, 0)
    points += {"ninguno": 0, "macrocalcificaciones": 1,
               "calcificaciones perifericas": 2, "focos puntiformes": 3}.get(echogenic_foci, 0)
    if points == 0:
        return "TIRADS 1"
    if points == 2:
        return "TIRADS 2"
    if points == 3:
        return "TIRADS 3"
    if 4 <= points <= 6:
        return "TIRADS 4"
    return "TIRADS 5"


_ALREADY_CLASSIFIED = {
    "BIRADS": re.compile(r"bi-?rads?\s*(us\s*)?\d", re.IGNORECASE),
    "TIRADS": re.compile(r"ti-?rads\s*\d", re.IGNORECASE),
}

CLASSIFICATION_REQUIREMENTS = {
    "mama": {
        "system": "BIRADS",
        "fields": [
            ("margins", extract_margin,
             "¿Márgenes del nódulo? (circunscriptos / indistintos / microlobulados / espiculados / irregulares)"),
            ("shape", extract_shape,
             "¿Forma del nódulo? (ovalada / redonda / irregular / más alta que ancha)"),
        ],
        "classify_fn": lambda margins, shape: classify_birads(margins, shape),
    },
    "tiroides": {
        "system": "TIRADS",
        "fields": [
            ("composition", extract_composition,
             "¿Composición del nódulo? (sólida / quística / mixta / espongiforme)"),
            ("echogenicity", extract_echogenicity,
             "¿Ecogenicidad del nódulo (no de la glándula)?"),
            ("shape", extract_shape,
             "¿Forma? (más ancho que alto / más alto que ancho)"),
            ("margin", extract_margin,
             "¿Márgenes? (lisos / indistintos / lobulados / extensión extratiroidea)"),
            ("echogenic_foci", extract_echogenic_foci,
             "¿Focos ecogénicos? (ninguno / macro / periféricas / puntiformes)"),
        ],
        "classify_fn": classify_tirads,
    },
}


def _find_classification_config(organ: Optional[str]) -> Optional[dict]:
    organ_lower = _strip_accents((organ or "").lower())
    for key, cfg in CLASSIFICATION_REQUIREMENTS.items():
        if _strip_accents(key) in organ_lower:
            return cfg
    return None


def check_classification_gap(findings: List[Finding]) -> List[DevilQuestion]:
    out = []
    for f in findings:
        if f.status != "ACTIVE" or not f.organ:
            continue
        cfg = _find_classification_config(f.organ)
        if not cfg:
            continue

        desc = f.description or ""
        already = _ALREADY_CLASSIFIED.get(cfg["system"])
        if already and already.search(desc):
            continue

        missing = {}
        for field_name, extractor, question_text in cfg["fields"]:
            if extractor(desc) is None:
                missing[field_name] = question_text

        if missing:
            out.append(DevilQuestion(
                finding=f,
                question=f"Para clasificar '{f.name}' con {cfg['system']}, faltan "
                          f"{len(missing)} de {len(cfg['fields'])} descriptores.",
                reason=f"Sistema {cfg['system']} requiere estos campos de forma "
                       f"explícita, no inferible.",
                rule_type="E",
                missing_fields=missing,
            ))
    return out


def classify_with_answers(organ: str, description: str, answers: dict) -> Optional[str]:
    cfg = _find_classification_config(organ)
    if not cfg:
        return None
    values = {}
    for field_name, extractor, _ in cfg["fields"]:
        values[field_name] = extractor(description) or answers.get(field_name)
    if any(v is None for v in values.values()):
        return None
    result = cfg["classify_fn"](**values)
    if result and contains_management_language(result):
        result = strip_to_classification_only(result)
    return result
_MIDE_PLURAL_HEADS = {
    "masas", "quistes", "nodulos", "polipos", "calculos", "abscesos", "tumores",
    "imagenes", "litos", "placas", "diverticulos", "ganglios", "hematomas",
    "lesiones", "calcificaciones", "adenopatias", "pliegues",
}


def _mide_clause(text: str, size_str: str) -> str:
    """", que mide X" / ", que miden X" según el texto hable de 'paredes' u otro plural."""
    plain = text.lower().translate(str.maketrans("áéíóú", "aeiou"))
    words = re.findall(r"[a-zñ]+", plain)
    plural = "paredes" in words or (bool(words) and words[0] in _MIDE_PLURAL_HEADS)
    return f", que miden {size_str}" if plural else f", que mide {size_str}"


_LINK_VERB_NOUNS = {
    "masa", "masas", "quiste", "quistes", "nodulo", "nodulos", "polipo", "polipos",
    "calculo", "calculos", "absceso", "abscesos", "tumor", "tumores", "imagen",
    "imagenes", "liquido", "barro", "lito", "litos", "trombo", "placa", "placas",
    "diverticulo", "diverticulos", "ganglio", "ganglios", "aneurisma", "edema",
    "hematoma", "hematomas", "aumento", "aumentos",
}
_LINK_VERB_SUFFIXES = (
    "cion", "ciones", "sion", "siones", "miento", "mientos", "dad", "dades",
    "ia", "itis", "osis", "iasis", "oma", "omas",
)


def _link_verb(text: str, organ: Optional[str], organ_present: bool) -> str:
    """
    " presenta" / " presentan" cuando hay que anteponer el órgano y el hallazgo
    arranca con un sustantivo ("Riñón derecho masa sólida" queda telegráfico).
    Vacío con participios, adjetivos o preposiciones ("disminuido de tamaño",
    "con masa..."), donde agregar el verbo sonaría mal.
    """
    if not organ or organ_present:
        return ""
    plain = text.strip().lower().translate(str.maketrans("áéíóú", "aeiou"))
    first = plain.split(" ")[0].strip(",.;:") if plain else ""
    if not first:
        return ""
    if first not in _LINK_VERB_NOUNS and not first.endswith(_LINK_VERB_SUFFIXES):
        return ""
    organ_words = organ.strip().lower().translate(str.maketrans("áéíóú", "aeiou")).split()
    last = organ_words[-1] if organ_words else ""
    plural = last.endswith(("es", "os", "as")) and last not in ("pancreas", "tiroides")
    return " presentan" if plural else " presenta"


def _lower_first(text: str) -> str:
    if len(text) > 1 and text[0].isupper() and not text[1].isupper():
        return text[0].lower() + text[1:]
    return text

_WALL_WORDS = {"pared", "paredes", "parietal", "parietales", "mural", "murales"}
_HOLLOW_WORDS = {
    "apendice", "vesicula", "biliar", "coledoco", "estomago", "esofago",
    "duodeno", "yeyuno", "ileon", "intestino", "colon", "recto", "sigma",
    "vejiga", "ureter", "uretra", "aorta", "arteria", "vena",
}


def _plain_words(text: Optional[str]) -> list:
    plain = (text or "").lower().translate(str.maketrans("áéíóú", "aeiou"))
    return re.findall(r"[a-zñ]+", plain)


def _measure_clause(text: str, size_str: str, organ: Optional[str] = None) -> str:
    """
    ", que mide X" / ", que miden X". Si el hallazgo habla de la pared (pared,
    paredes, parietal, mural) agrega "de espesor", y "de espesor parietal" cuando
    el órgano es hueco. Si el texto ya dice "espesor", no lo repite.
    """
    words = _plain_words(text)
    plural = "paredes" in words or (bool(words) and words[0] in _MIDE_PLURAL_HEADS)
    verb = "miden" if plural else "mide"
    suffix = ""
    if any(w in _WALL_WORDS for w in words) and "espesor" not in words:
        hollow = any(w in _HOLLOW_WORDS for w in _plain_words(organ))
        suffix = " de espesor parietal" if hollow else " de espesor"
    return f", que {verb} {size_str}{suffix}"


def _ask_measure(text: Optional[str]) -> str:
    if any(w in _WALL_WORDS for w in _plain_words(text)):
        return "¿Cuánto mide el espesor de la pared?"
    return "¿Tenés la dimensión?"
_SIDE_LABELS = {
    "derecho": "derecho", "derecha": "derecho", "der": "derecho",
    "izquierdo": "izquierdo", "izquierda": "izquierdo", "izq": "izquierdo",
}


def _describe_finding_for_impression(f: Finding) -> str:
    """
    Arma la frase de sintesis para un finding usando sus campos
    estructurados (organ, side, size_mm), no solo el texto libre de
    description -- mismo patron de redaccion ("[Organo] [lado]
    [hallazgo], mide X mm.") que _sentence_for_side en
    line_based_report_engine.py, para que la Impresion Diagnostica
    sugerida no se lea distinto al cuerpo del informe para el mismo
    hallazgo. Corregido dos veces en produccion: primero porque
    size_mm/side podian faltar del todo del texto libre (2026-09-25),
    despues porque ademas faltaba el nombre del organo (2026-09-26) --
    el caso del bazo funcionaba por casualidad, porque su description
    ya incluia el sujeto ("coleccion liquida periesplenica"); el del
    riñon no, porque su description es solo un adjetivo suelto
    ("disminuido de tamaño...") sin sujeto propio.
    """
    desc = measure_engine.prepare_description((f.description or f.name or "").strip().rstrip("."), f.size_mm)
    organ = f.organ.strip() if f.organ else None
    side_label = _SIDE_LABELS.get((f.side or "").strip().lower())

    desc_no_accents = _strip_accents(desc.lower())
    organ_present = bool(organ) and (
        _strip_accents(organ.lower()) in desc_no_accents
        or _organ_meaningfully_present(organ, desc_no_accents)
    )
    side_present = bool(side_label) and side_label.rstrip("o") in desc_no_accents

    subject_parts = []
    if organ and not organ_present:
        subject_parts.append(organ)
    if side_label and not side_present and organ and not organ_present:
        subject_parts.append(measure_engine.agree_side(organ, side_label))

    if subject_parts:
        subject = " ".join(subject_parts)
        text = f"{subject}{measure_engine.link_verb(desc, organ, organ_present)} {_lower_first(desc)}".strip() if desc else subject
    else:
        text = desc

    if f.size_mm is not None and not _MEASUREMENT_IN_TEXT_RE.search(text):
        try:
            size_str = f"{float(f.size_mm):g} mm"
        except (TypeError, ValueError):
            size_str = None
        if size_str:
            text = f"{text}{measure_engine.measure_clause(desc, size_str, f.organ)}" if text else f"mide {size_str}"

    if not text:
        return ""
    text = measure_engine.with_side(text, f.side)
    return text[0].upper() + text[1:] + "."


def _tier1_resumen(active: List[Finding]) -> str:
    sentences = [_describe_finding_for_impression(f) for f in active if (f.description or f.name)]
    return " ".join(sentences)


def _tier3_candidate(active: List[Finding]) -> Optional[str]:
    for f in active:
        cfg = _find_classification_config(f.organ)
        if not cfg:
            continue
        desc = f.description or ""
        missing = {name: q for name, extractor, q in cfg["fields"] if extractor(desc) is None}
        if missing:
            continue
        result = classify_with_answers(f.organ, desc, {})
        if result:
            return f"{f.name}: {result}"
    return None


def suggest_impression_level(
    findings: List[Finding], quality_issues: Optional[list] = None
) -> Optional[DevilQuestion]:
    active = [f for f in findings if f.status == "ACTIVE"]
    if not active:
        return None

    quality_issues = quality_issues or []
    flagged_names = {qi.finding.name for qi in quality_issues if getattr(qi, "finding", None)}
    flagged_active = [f.name for f in active if f.name in flagged_names]
    has_flag = bool(flagged_active)

    tier1 = _tier1_resumen(active)
    tier3 = None if has_flag else _tier3_candidate(active)

    if has_flag:
        question = (f"Control de calidad marcó: {', '.join(flagged_active)}. "
                    "Revisalo antes de cerrar la impresión diagnóstica.")
        reason = "Hallazgo marcado por el control de calidad."
    elif len(active) == 1 and tier3:
        question = ("La impresión diagnóstica todavía no está redactada. "
                    "Podés cerrarla con el resumen o con la clasificación. ¿Cuál preferís?")
        reason = "Un hallazgo activo con clasificación disponible."
    elif len(active) >= 2:
        question = (f"La impresión diagnóstica todavía no está redactada. "
                    f"Hay {len(active)} hallazgos activos; el resumen sugerido los junta en un solo párrafo.")
        reason = f"{len(active)} hallazgos activos sin impresión redactada."
    else:
        question = ("La impresión diagnóstica todavía no está redactada. "
                    "¿Usamos este resumen?")
        reason = "Un hallazgo activo sin impresión redactada."

    return DevilQuestion(
        finding=None,
        question=question,
        reason=reason,
        rule_type="F",
        closure_candidates={"nivel_1": tier1, "nivel_2": None, "nivel_3": tier3},
    )


def review(
    findings: List[Finding], modality: str, quality_issues: Optional[list] = None
) -> List[DevilQuestion]:
    questions = []
    questions += check_missing_laterality(findings); questions += check_missing_measurement(findings)
    questions += check_terminology(findings, modality)
    questions += check_classification_gap(findings)
    f_question = suggest_impression_level(findings, quality_issues)
    if f_question:
        questions.append(f_question)
    return questions
