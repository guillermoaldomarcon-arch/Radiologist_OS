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

== MEDIDA_CONFIRMADA marker (added) ==

When the radiologist answers a devil-advocate question about a
missing measurement, the frontend appends a structured line to the
dictation instead of a bare number:

    [MEDIDA_CONFIRMADA: <finding description> = <value> mm]

This exists to remove ambiguity when the dictation already contains
more than one finding without a measurement -- a bare number appended
at the end of free text left the AI to guess which finding it
belonged to (seen in production: a measurement meant for one finding
silently attached itself to a different one). The prompt below
treats this marker as a literal instruction, not prose to interpret:
it must be applied ONLY to the finding it names, never inferred by
proximity or order.
"""

import json
import re
from typing import Callable, List, Optional

from finding import Finding
import marker_engine


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
  "is_pathological": boolean,
  "confirmed_line_id": string or null, "paired": boolean or null
}}

Reglas estrictas:
- "description" debe ser un fragmento literal o casi literal del texto original -- NUNCA inventes ni agregues información que no esté en el dictado.
- Si el dictado no menciona una medida explícita en mm/cm, "size_mm" debe ser null -- NUNCA estimes ni inventes un valor.
- Si no hay un hallazgo claro, no incluyas esa frase.
- Regla especial para marcadores [MEDIDA_CONFIRMADA: <descripción> = <valor> mm]: si el dictado contiene una línea con ese formato exacto, es una instrucción literal del radiólogo, NO un hallazgo nuevo. Buscá, entre los hallazgos que ya identificaste en el resto del dictado, aquel cuya descripción coincida (razonablemente, no necesariamente palabra por palabra) con el texto entre "MEDIDA_CONFIRMADA:" y "=", y asignale ese "size_mm" a ESE hallazgo específico. NUNCA se lo asignes a otro hallazgo distinto, aunque esté más cerca en el texto. Si no encontrás ningún hallazgo cuya descripción coincida razonablemente, ignorá el marcador (no inventes un hallazgo nuevo solo por el marcador). El marcador en sí NUNCA debe aparecer como un hallazgo propio en tu respuesta.
- Regla especial para marcadores [UBICACION_CONFIRMADA: <descripción> = <line_id>]: igual tratamiento que MEDIDA_CONFIRMADA -- es una instrucción literal del radiólogo, NO un hallazgo nuevo. Buscá, entre los hallazgos que ya identificaste, aquel cuya descripción coincida razonablemente con el texto entre "UBICACION_CONFIRMADA:" y "=", y asignale ese valor al campo "confirmed_line_id" de ESE hallazgo específico. Nunca se lo asignes a otro hallazgo distinto. Si no encontrás coincidencia razonable, ignorá el marcador. El marcador en sí nunca debe aparecer como hallazgo propio.
- El valor de line_id dentro de un marcador [UBICACION_CONFIRMADA: ... = <line_id>] es un identificador interno de ubicación, NUNCA una pista clínica. Aunque ese valor coincida textualmente con el nombre de un órgano (ej. "higado"), NO debe influir en el campo "organ" de ningún hallazgo -- el "organ" de cada hallazgo se determina únicamente por lo que el hallazgo mismo describe clínicamente, nunca por el line_id al que se lo está asignando.
- Campo "paired": true si la estructura anatómica del hallazgo existe a ambos lados del cuerpo (riñón, glándula suprarrenal, ovario, testículo, mama, pezón, axila, pulmón, mano, brazo, hombro, rodilla, etc.), false si es única o de línea media (hígado, bazo, páncreas, vejiga, próstata, útero, aorta), null si no estás seguro. Se decide con conocimiento anatómico, no por lo que diga el dictado.
- Regla especial para marcadores [LATERALIDAD_CONFIRMADA: <descripción> = derecho|izquierdo|bilateral]: igual tratamiento que MEDIDA_CONFIRMADA -- es una instrucción literal del radiólogo, NO un hallazgo nuevo. Buscá, entre los hallazgos que ya identificaste, aquel cuya descripción coincida razonablemente con el texto entre "LATERALIDAD_CONFIRMADA:" y "=", y asignale ese valor al campo "side" de ESE hallazgo específico. Nunca se lo asignes a otro hallazgo distinto. Si no encontrás coincidencia razonable, ignorá el marcador. El marcador en sí nunca debe aparecer como hallazgo propio.
- Regla especial para hallazgos adicionales: si una frase del dictado empieza con "hallazgo adicional" u "otro hallazgo" (por ejemplo "Hallazgo adicional: adenopatía axilar de 14 mm bilateral"), el radiólogo indica que ese hallazgo no pertenece a este estudio. Devolvelo como un hallazgo normal, con "confirmed_line_id": "otros_hallazgos", y en "description" poné solo el contenido, sin las palabras "hallazgo adicional" ni "otro hallazgo".
- Respondé ÚNICAMENTE con un array JSON, sin texto adicional, sin markdown.

Dictado:
\"\"\"{dictation_text}\"\"\""""

    raw_response = _call_until_json(call_claude, prompt)

    try:
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.replace("json", "", 1).strip()
        data = json.loads(cleaned)
    except (json.JSONDecodeError, AttributeError):
        raise ValueError("El extractor devolvió una respuesta que no se pudo leer. Probá de nuevo.")

    if not isinstance(data, list):
        raise ValueError("El extractor devolvió una respuesta que no se pudo leer. Probá de nuevo.")

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
                confirmed_line_id=raw.get("confirmed_line_id"), paired=(raw.get("paired") if isinstance(raw.get("paired"), bool) else None),
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

_EXTRA_ID = "otros_hallazgos"
_EXTRA_MARKER_RE = re.compile(
    r"\[UBICACION_CONFIRMADA:\s*(.+?)\s*=\s*otros_hallazgos\s*\]", re.IGNORECASE | re.DOTALL
)
_EXTRA_KEYWORD_RE = re.compile(
    r"(?:hallazgo adicional|otro hallazgo)\s*[:\-–,]?\s*((?:[^.\n\[]|\.\d)+)", re.IGNORECASE
)
_EXTRA_PREFIX_RE = re.compile(
    r"^\s*(?:hallazgo adicional|otro hallazgo)\s*[:\-–,]?\s*", re.IGNORECASE
)


def _call_until_json(call_claude, prompt, attempts=2):
    """Llama a Claude y, si la respuesta no es una lista JSON válida, reintenta una vez."""
    raw = ""
    for _ in range(attempts):
        raw = call_claude(prompt)
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`").replace("json", "", 1).strip()
            if isinstance(json.loads(cleaned), list):
                return raw
        except (json.JSONDecodeError, AttributeError):
            continue
    return raw


def _word_set(text):
    return {w for w in re.findall(r"[a-zñ0-9]+", _strip_accents((text or "").lower())) if len(w) > 2}


def _similar(a, b):
    wa, wb = _word_set(a), _word_set(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def _extra_descriptions(dictation_text):
    """Textos que el médico dejó como 'hallazgo adicional' (marcador o frase), sin repetidos."""
    found = [m.group(1).strip() for m in _EXTRA_MARKER_RE.finditer(dictation_text)]
    found += [m.group(1).strip(" .") for m in _EXTRA_KEYWORD_RE.finditer(dictation_text)]
    out = []
    for text in found:
        if text and not any(_similar(text, seen) for seen in out):
            out.append(text)
    return out


def _ensure_extra_findings(findings, dictation_text):
    """
    Garantiza que cada hallazgo adicional pedido por el médico exista como
    Finding con confirmed_line_id='otros_hallazgos', sin depender de que la IA
    lo haya devuelto bien: si ya hay uno parecido se lo marca, y si no existe
    se crea con el texto literal. Un hallazgo dictado nunca debe desaparecer.
    """
    for text in _extra_descriptions(dictation_text):
        if any(f.confirmed_line_id == _EXTRA_ID and _similar(f.description or "", text) for f in findings):
            continue
        match = next(
            (f for f in findings if f.confirmed_line_id != _EXTRA_ID and _similar(f.description or "", text)),
            None,
        )
        if match is not None:
            match.confirmed_line_id = _EXTRA_ID
            match.status = "ACTIVE"
            continue
        size_match = _MEASUREMENT_PATTERN.search(text)
        size_mm = None
        if size_match:
            size_mm = float(size_match.group(1).replace(",", "."))
            if size_match.group(2).lower() == "cm":
                size_mm *= 10.0
        findings.append(Finding(
            name=text, organ=None, description=text, size_mm=size_mm,
            certainty="HIGH", status="ACTIVE", confirmed_line_id=_EXTRA_ID,
        ))
    for f in findings:
        if f.confirmed_line_id == _EXTRA_ID and f.description:
            f.description = _EXTRA_PREFIX_RE.sub("", f.description)


def parse(
    dictation_text: str,
    call_claude=None,
    organ_hints: Optional[List[str]] = None,
) -> List[Finding]:
    hints = organ_hints if organ_hints is not None else _DEFAULT_ORGAN_HINTS

    if call_claude is not None:
        raw_findings = _ai_extract_findings(marker_engine.text_for_ai(dictation_text), hints, call_claude)
        return marker_engine.finalize(ai_findings_to_objects(raw_findings, dictation_text), dictation_text, lambda: ai_findings_to_objects(_ai_extract_findings(marker_engine.text_for_ai(dictation_text), hints, call_claude), dictation_text))

    findings: List[Finding] = []
    sentences = [
        s.strip() for s in re.split(r"(?<=[.;])\s+", dictation_text) if s.strip()
    ]
    for sentence in sentences:
        finding = _extract_with_rules_only(sentence, hints)
        if finding is not None:
            findings.append(finding)

    return findings
