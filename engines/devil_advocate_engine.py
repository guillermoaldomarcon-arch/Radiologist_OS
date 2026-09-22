"""
devil_advocate_engine.py

Raises questions about a report's Finding objects before the
radiologist signs -- never modifies anything, only informs.
"""

from __future__ import annotations
import re
from typing import Callable, List, Optional

from finding import Finding

_ACCENT_MAP = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")


def _strip_accents(text: str) -> str:
    return text.translate(_ACCENT_MAP)


_MANAGEMENT_PATTERNS = [
    r"se recomienda\s+(control|seguimiento|repetir|evaluar|biopsia|derivar)",
    r"sugerir\w*\s+(control|seguimiento|biopsia|evaluar)",
    r"control\s+en\s+\d+\s*(mes|año|semana)",
    r"seguimiento\s+a\s+\d+\s*(mes|año|semana)",
    r"correlacionar\s+con\s+(cl[ií]nica|laboratorio)\s+y\s+(tratar|actuar)",
    r"deriva\w*\s+a\s+(especialista|cirug[ií]a|urgencias)",
]
_MANAGEMENT_RE = re.compile("|".join(_MANAGEMENT_PATTERNS), re.IGNORECASE)


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


def check_missing_measurement(findings: List[Finding]) -> List[DevilQuestion]:
    out = []
    for f in findings:
        if f.status == "ACTIVE" and f.size_mm is None:
            out.append(DevilQuestion(
                finding=f,
                question=f"Mencionaste '{f.name}' sin medida. ¿Tenés la dimensión?",
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
    if "lobulad" in t or "irregular" in t:
        return "lobulados/irregulares"
    if "extratiroide" in t:
        return "extension extratiroidea"
    if "circunscript" in t or " liso" in t:
        return "circunscriptos/lisos"
    return None


def extract_shape(text: str) -> Optional[str]:
    t = text.lower()
    if "mas alto que ancho" in t or "más alto que ancho" in t:
        return "mas alto que ancho"
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
             "¿Márgenes del nódulo? (circunscriptos / indistintos / microlobulados / espiculados)"),
            ("shape", extract_shape,
             "¿Forma del nódulo? (ovalada-redonda / irregular)"),
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


def _tier1_resumen(active: List[Finding]) -> str:
    sentences = []
    for f in active:
        text = (f.description or f.name).strip().rstrip(".")
        if text:
            text = text[0].upper() + text[1:]
        sentences.append(text + ".")
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
    has_flag = any(f.name in flagged_names for f in active)

    tier1 = _tier1_resumen(active)
    tier3 = None if has_flag else _tier3_candidate(active)

    if has_flag:
        question = ("Hay hallazgos marcados por Quality Engine -- resolvelos antes "
                     "de elegir el nivel de cierre de la impresión.")
    elif len(active) == 1 and tier3:
        question = (f"El informe no genera Impresión Diagnóstica (el pipeline actual "
                     f"no la construye). Un solo hallazgo con clasificación disponible "
                     f"-- Nivel 3 parece razonable. ¿Cuál preferís?")
    elif len(active) >= 2:
        question = (f"El informe no genera Impresión Diagnóstica. Hay {len(active)} "
                     f"hallazgos activos -- Nivel 2 (síntesis) puede ser más claro que "
                     f"listarlos por separado. ¿Cuál preferís?")
    else:
        question = ("El informe no genera Impresión Diagnóstica. Nivel 1 (resumen) "
                     "puede alcanzar para este caso. ¿Cuál preferís?")

    return DevilQuestion(
        finding=None,
        question=question,
        reason=f"{len(active)} hallazgo(s) activo(s), flags={has_flag}, "
               f"clasificación disponible={tier3 is not None}.",
        rule_type="F",
        closure_candidates={"nivel_1": tier1, "nivel_2": None, "nivel_3": tier3},
    )


def review(
    findings: List[Finding], modality: str, quality_issues: Optional[list] = None
) -> List[DevilQuestion]:
    questions = []
    questions += check_missing_measurement(findings)
    questions += check_terminology(findings, modality)
    questions += check_classification_gap(findings)
    f_question = suggest_impression_level(findings, quality_issues)
    if f_question:
        questions.append(f_question)
    return questions

