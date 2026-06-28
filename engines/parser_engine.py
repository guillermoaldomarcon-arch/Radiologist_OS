"""
parser_engine.py

Converts free-text dictation into a list of Finding objects.

== DESIGN v2 (changed from v1) ==

Previous design (v1, see parser_engine_v1_backup.py): rules-first,
AI-as-fallback-only. This worked for clear structural patterns
(explicit measurement + organ name from a fixed vocabulary) but
failed on real dictation like "lesión hipodensa paraventricular
derecha de aspecto isquémico secuelar" -- a clinically unambiguous
pathological finding that doesn't literally contain any word from a
fixed organ list, and that requires actual medical knowledge
(hipodensa + isquémico + secuelar = sequela of an ischemic event) to
recognize as a finding at all.

Current design (v2), per Guille's explicit decision: the AI is now
PRIMARY for recognizing whether a sentence describes a pathological
finding and what its organ/location/laterality/measurement are -- it
uses real medical knowledge, not a fixed vocabulary list. Rules no
longer decide WHETHER something is a finding; they run AFTER the AI
call, as a verification step, checking whether each specific claim
the AI made (a measurement, a laterality term, an organ name) is
actually present in the original text.

Design principle (per project philosophy), reinterpreted for v2:
"Never increase certainty" no longer means "AI output = LOW
certainty by default, rules = HIGH by default." It means: certainty
should reflect whether each individual claim is verifiable against
the source text, regardless of whether AI or rules produced it. A
measurement the AI extracted that IS literally in the text is just
as verifiable as one a regex would have found. A claim that is NOT
literally in the text (an inference, even a clinically reasonable
one) is flagged with lower certainty and is exactly the kind of
thing the radiologist should glance at before signing.

Rules are NOT removed -- they still do two important jobs:
1. Per-claim verification (see _verify_finding_against_text below).
2. A safety-net pass over the AI's output for negation/normality
   phrases the AI might have mis-classified as pathological (or vice
   versa) -- see _cross_check_negation below.

If `call_claude` is not provided, this module CANNOT recognize
pathology from free text (the old rules-only path is preserved as a
literal fallback only for offline/no-API testing -- see
_extract_with_rules_only, used only when call_claude is None). This
is a known, accepted limitation: without AI, the system only catches
clinical content matching the legacy fixed vocabulary.
"""

import json
import re
from typing import Callable, List, Optional

from finding import Finding


_MEASUREMENT_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mm|cm)\b", re.IGNORECASE
)

_LATERALITY_PATTERN = re.compile(
    r"\b(derech[oa]|izquierd[oa]|bilateral)\b", re.IGNORECASE
)

_NEGATION_PATTERN = re.compile(
    r"\b("
    r"sin evidencia de|no se observan?|no se identifican?|sin"
    r"|conservad[oa]s?"
    r"|normal(?:es)?"
    r"|sin particularidades"
    r"|dentro de l[íi]mites normales"
    r"|sin alteraciones"
    r"|sin hallazgos patol[óo]gicos"
    r"|de aspecto habitual"
    r"|preservad[oa]s?"
    r"|no hay\b"
    r"|uniforme[s]?"
    r"|no evidencian?"
    r")\b",
    re.IGNORECASE,
)

_ACCENT_MAP = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")


def _strip_accents(text: str) -> str:
    return text.translate(_ACCENT_MAP)


def _singularize_simple(word: str) -> str:
    def _singularize_word(w: str) -> str:
        if len(w) > 2 and w[-1] == "s" and w[-2] in "aeiouáéíóú":
            return w[:-1]
        return w

    words = word.strip().lower().split()
    return " ".join(_singularize_word(w) for w in words)


def _organ_hint_matches(hint: str, sentence_lower: str) -> bool:
    hint_lower = hint.lower()
    sentence_no_accents = _strip_accents(sentence_lower)
    hint_no_accents = _strip_accents(hint_lower)

    if hint_lower in sentence_lower:
        return True
    if hint_no_accents in sentence_no_accents:
        return True

    singular_hint = _singularize_simple(hint_lower)
    singular_hint_no_accents = _strip_accents(singular_hint)

    if singular_hint != hint_lower and singular_hint in sentence_lower:
        return True
    if singular_hint_no_accents in sentence_no_accents:
        return True

    return False


_DEFAULT_ORGAN_HINTS = [
    "parénquima", "parenquima", "ventrículo", "ventriculo",
    "cisterna", "calota", "senos paranasales", "fosa posterior",
    "sustancia blanca", "sustancia gris", "tronco encefálico",
    "tronco encefalico", "cerebelo", "línea media", "linea media",
]


def _ai_extract_findings(
    dictation_text: str, organ_hints: List[str], call_claude: Callable[[str], str]
) -> List[dict]:
    hints_text = ", ".join(organ_hints)

    prompt = f"""Eres un asistente que extrae hallazgos radiológicos de un dictado médico en español, usando conocimiento médico real (terminología, patrones de enfermedad, sinónimos clínicos). NO te limites a buscar palabras exactas de una lista -- reconocé el significado clínico real, incluyendo localizaciones indirectas (ej. "paraventricular" implica relación con el ventrículo) y términos descriptivos de patología (ej. "hipodensa", "isquémico secuelar", "de aspecto inespecífico").

Regiones/órganos típicos de este tipo de estudio (lista de referencia, NO exhaustiva -- puede haber otros): {hints_text}

Para CADA hallazgo distinto (patológico O explícitamente normal) en el dictado, devolvé un objeto con estos campos exactos:

{{
  "organ": string,
  "location": string or null,
  "side": string or null,
  "size_mm": number or null,
  "description": string,
  "is_pathological": boolean
}}

Reglas estrictas:
- "description" debe ser un fragmento literal o casi literal del texto original -- NUNCA inventes ni agregues información que no esté en el dictado.
- Si el dictado no menciona una medida explícita en mm/cm, "size_mm" debe ser null -- NUNCA estimes ni inventes un valor.
- Si no hay un hallazgo claro, no incluyas esa frase.
- Respondé ÚNICAMENTE con un array JSON, sin texto adicional, sin markdown.

Dictado:
\"\"\"{dictation_text}\"\"\""""

    raw_response = call_claude(prompt)

    try:
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.replace("json", "", 1).strip()
        data = json.loads(cleaned)
    except (json.JSONDecodeError, AttributeError):
        return []

    if not isinstance(data, list):
        return []

    return data


def _verify_finding_against_text(raw_finding: dict, dictation_text: str) -> str:
    text_lower = dictation_text.lower()
    text_no_accents = _strip_accents(text_lower)

    size_mm = raw_finding.get("size_mm")
    if size_mm is not None:
        found_measurement = False
        for match in _MEASUREMENT_PATTERN.finditer(dictation_text):
            raw_value = match.group(1).replace(",", ".")
            unit = match.group(2).lower()
            matched_mm = float(raw_value) * (10.0 if unit == "cm" else 1.0)
            if abs(matched_mm - size_mm) < 0.01:
                found_measurement = True
                break
        if not found_measurement:
            return "LOW"

    side = raw_finding.get("side")
    if side:
        side_stem = _strip_accents(side.lower()).rstrip("oa")
        if side_stem not in text_no_accents:
            return "LOW"

    description = raw_finding.get("description", "")
    description_words = set(_strip_accents(description.lower()).split())
    overlap = [w for w in description_words if w in text_no_accents]
    overlap_ratio = len(overlap) / max(len(description_words), 1)

    if overlap_ratio < 0.5:
        return "LOW"
    if overlap_ratio < 0.85:
        return "MODERATE"

    return "HIGH"


def _cross_check_negation(raw_finding: dict, dictation_text: str) -> bool:
    description = raw_finding.get("description", "")
    is_pathological = raw_finding.get("is_pathological", True)

    has_negation = bool(_NEGATION_PATTERN.search(description))

    if has_negation and is_pathological:
        return False

    return True


def ai_findings_to_objects(
    raw_findings: List[dict], dictation_text: str
) -> List[Finding]:
    findings: List[Finding] = []

    for raw in raw_findings:
        organ = raw.get("organ")
        if not organ:
            continue

        certainty = _verify_finding_against_text(raw, dictation_text)
        negation_check_passed = _cross_check_negation(raw, dictation_text)

        is_pathological = raw.get("is_pathological", True)
        status = "ACTIVE" if is_pathological else "NO_FINDING"

        if not negation_check_passed:
            status = "FLAGGED"
            certainty = "LOW"

        findings.append(
            Finding(
                name=organ,
                organ=organ,
                location=raw.get("location"),
                side=raw.get("side"),
                size_mm=raw.get("size_mm") if is_pathological else None,
                description=raw.get("description", ""),
                certainty=certainty,
                status=status,
            )
        )

    return findings


def _extract_with_rules_only(sentence: str, organ_hints: List[str]) -> Optional[Finding]:
    measurement_match = _MEASUREMENT_PATTERN.search(sentence)
    laterality_match = _LATERALITY_PATTERN.search(sentence)
    negation_match = _NEGATION_PATTERN.search(sentence)

    organ = next(
        (hint for hint in organ_hints if _organ_hint_matches(hint, sentence.lower())),
        None,
    )

    if organ is None:
        return None

    if negation_match:
        return Finding(
            name=organ,
            organ=organ,
            side=laterality_match.group(1).lower() if laterality_match else None,
            size_mm=None,
            description=sentence.strip(),
            certainty="HIGH",
            status="NO_FINDING",
        )

    if not (measurement_match or laterality_match):
        return None

    size_mm = None
    if measurement_match:
        raw_value = measurement_match.group(1).replace(",", ".")
        unit = measurement_match.group(2).lower()
        size_mm = float(raw_value)
        if unit == "cm":
            size_mm *= 10.0

    side = laterality_match.group(1).lower() if laterality_match else None

    return Finding(
        name=organ,
        organ=organ,
        side=side,
        size_mm=size_mm,
        description=sentence.strip(),
        certainty="HIGH" if (measurement_match or laterality_match) else "MODERATE",
        status="ACTIVE",
    )


def parse(
    dictation_text: str,
    call_claude=None,
    organ_hints: Optional[List[str]] = None,
) -> List[Finding]:
    hints = organ_hints if organ_hints is not None else _DEFAULT_ORGAN_HINTS

    if call_claude is not None:
        raw_findings = _ai_extract_findings(dictation_text, hints, call_claude)
        return ai_findings_to_objects(raw_findings, dictation_text)

    findings: List[Finding] = []
    sentences = [
        s.strip() for s in re.split(r"(?<=[.;])\s+", dictation_text) if s.strip()
    ]
    for sentence in sentences:
        finding = _extract_with_rules_only(sentence, hints)
        if finding is not None:
            findings.append(finding)

    return findings
