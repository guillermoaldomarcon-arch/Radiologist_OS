"""
parser_engine.py

Converts free-text dictation into a list of Finding objects.

Design principle (per project philosophy):
Rules first, AI only as fallback. Never invent findings, measurements,
or laterality. If a sentence cannot be confidently parsed by rules and
the AI fallback also cannot extract a clear Finding, the sentence is
skipped and logged — NOT guessed.

MVP scope:
- Rule-based extraction handles clear, structured patterns (explicit
  measurements with units, explicit laterality, explicit negation).
- AI fallback (Claude) is used ONLY for sentences that contain
  apparent clinical content but did not match any rule. The AI is
  asked to return structured JSON only, never prose.
- Anything extracted via the AI fallback is marked with
  certainty="LOW" unless a rule independently confirms the same
  finding, since AI-assisted extraction is inherently less verifiable
  than a deterministic rule match.
"""

import json
import re
from typing import List, Optional

from finding import Finding


# ---------------------------------------------------------------------------
# Rule patterns
# ---------------------------------------------------------------------------

# Matches things like "15 mm", "2.3 cm", "1,5 cm"
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
    r")\b",
    re.IGNORECASE,
)

_ACCENT_MAP = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")


def _strip_accents(text: str) -> str:
    """
    Removes Spanish accent marks for comparison purposes only (never
    used to alter what gets stored in a Finding's description — only
    to make organ-hint matching tolerant of dictation/typing
    inconsistencies like "oseas" vs "óseas", both of which are common
    in real fast-typed dictation).
    """
    return text.translate(_ACCENT_MAP)


def _singularize_simple(word: str) -> str:
    """
    Deliberately simple singular/plural normalization for Spanish —
    NOT a linguistic stemmer. Only handles the common regular case:
    a word ending in a vowel followed by "s" (e.g. "discos" ->
    "disco", "vesículas" -> "vesícula").

    Handles multi-word terms (e.g. "discos intervertebrales") by
    normalizing each word independently, since Spanish adjectives
    agree in number with their noun ("disco intervertebral" /
    "discos intervertebrales" both need normalizing, not just the
    head noun).

    This intentionally does NOT attempt irregular cases (e.g.
    "tórax", which already ends in "x" and has no separate plural
    form in this context, or "lápiz"/"lápices"-style changes). Those
    cases must be handled explicitly by listing both forms in the
    template's expected_organs_or_regions — silently guessing at
    irregular pluralization is the kind of unverified assumption this
    project's philosophy avoids. This function only removes
    ambiguity in the common, safe case; it does not try to be
    linguistically complete.
    """
    def _singularize_word(w: str) -> str:
        if len(w) > 2 and w[-1] == "s" and w[-2] in "aeiouáéíóú":
            return w[:-1]
        return w

    words = word.strip().lower().split()
    return " ".join(_singularize_word(w) for w in words)


def _organ_hint_matches(hint: str, sentence_lower: str) -> bool:
    """
    Matches an organ_hint against a sentence, tolerant of:
    - simple regular singular/plural differences (see _singularize_simple)
    - presence/absence of accent marks (e.g. "oseas" vs "óseas"),
      common in fast-typed real dictation.
    """
    hint_lower = hint.lower()
    sentence_no_accents = _strip_accents(sentence_lower)
    hint_no_accents = _strip_accents(hint_lower)

    if hint_lower in sentence_lower:
        return True
    if hint_no_accents in sentence_no_accents:
        return True

    # Try matching the singularized hint against the sentence, and
    # the singularized sentence against the hint — covers both
    # directions without needing to singularize every word in the
    # sentence individually. Checked both with and without accents.
    singular_hint = _singularize_simple(hint_lower)
    singular_hint_no_accents = _strip_accents(singular_hint)

    if singular_hint != hint_lower and singular_hint in sentence_lower:
        return True
    if singular_hint_no_accents in sentence_no_accents:
        return True

    return False


# Minimal fallback vocabulary, used ONLY if no organ_hints list is
# provided by the caller. In normal operation, callers should pass
# the `expected_organs_or_regions` list from the relevant template's
# JSON definition (see template_engine.load_template), so the parser
# recognizes the correct vocabulary for whatever study type is being
# parsed instead of being limited to a single hardcoded list.
_DEFAULT_ORGAN_HINTS = [
    "parénquima", "parenquima", "ventrículo", "ventriculo",
    "cisterna", "calota", "senos paranasales", "fosa posterior",
    "sustancia blanca", "sustancia gris", "tronco encefálico",
    "tronco encefalico", "cerebelo", "línea media", "linea media",
]


def _looks_clinical(sentence: str, organ_hints: List[str]) -> bool:
    """
    Heuristic: does this sentence look like it contains clinical
    content worth trying to parse, as opposed to boilerplate
    (e.g. "Técnica: TC de cerebro sin contraste.")?
    Used only to decide whether to bother with the AI fallback —
    never used to create a Finding directly.
    """
    lowered = sentence.lower()
    if any(_organ_hint_matches(hint, lowered) for hint in organ_hints):
        return True
    if _MEASUREMENT_PATTERN.search(sentence):
        return True
    return False


def _extract_with_rules(sentence: str, organ_hints: List[str]) -> Optional[Finding]:
    """
    Attempts to build a Finding using only deterministic patterns.
    Returns None if the sentence doesn't match a clear, confident
    pattern — it does NOT guess.

    Negation handling (Option B — explicit traceability):
    A sentence like "Cisterna basal sin alteraciones." does NOT
    describe a pathological finding. It describes an organ/region
    that WAS evaluated and found normal. This is recorded as a
    Finding with status="NO_FINDING" rather than being silently
    dropped, so downstream engines (especially Followup) can later
    tell "evaluated and normal" apart from "never evaluated".

    A NO_FINDING Finding never carries a measurement or laterality
    from a positive pattern match — if the sentence has both a
    negation AND a measurement (e.g. "sin nódulos mayores a 5 mm"),
    the negation takes precedence and the measurement is treated as
    part of the negated description, not as a positive measurement.
    """
    measurement_match = _MEASUREMENT_PATTERN.search(sentence)
    laterality_match = _LATERALITY_PATTERN.search(sentence)
    negation_match = _NEGATION_PATTERN.search(sentence)

    organ = next(
        (hint for hint in organ_hints if _organ_hint_matches(hint, sentence.lower())),
        None,
    )

    if organ is None:
        return None

    # Negation takes precedence: this is a "no pathological finding"
    # record, not a positive finding, regardless of whether a
    # measurement or laterality term also appears in the sentence.
    if negation_match:
        return Finding(
            name=organ,
            organ=organ,
            side=laterality_match.group(1).lower() if laterality_match else None,
            size_mm=None,  # never attach a measurement to a negation
            description=sentence.strip(),
            certainty="HIGH",  # explicit negation is a clear, confident pattern
            status="NO_FINDING",
        )

    # No negation: rule only fires for a positive finding when we have
    # an organ hint AND at least one of (measurement, laterality).
    # Anything weaker is left for the AI fallback rather than guessed.
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


def _extract_with_ai(sentence: str, call_claude) -> Optional[Finding]:
    """
    AI fallback. `call_claude` is an injected function with signature
    (prompt: str) -> str, so this module stays testable without a
    live API dependency.

    Asks for STRICT JSON only. If the response is not valid JSON, or
    is missing the minimum required field ("name"/"organ"), this
    returns None rather than guessing.
    """
    prompt = f"""Extract a single radiological finding from this sentence,
if one is clearly present. Respond with ONLY a JSON object, no prose,
no markdown fences. Use this exact schema:

{{
  "organ": string or null,
  "location": string or null,
  "side": string or null,
  "size_mm": number or null,
  "description": string,
  "present": boolean
}}

If no clear finding is present, set "present": false and leave other
fields null except "description" (copy the sentence as-is).

Sentence: \"\"\"{sentence}\"\"\""""

    raw_response = call_claude(prompt)

    try:
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.replace("json", "", 1).strip()
        data = json.loads(cleaned)
    except (json.JSONDecodeError, AttributeError):
        return None

    if not data.get("present", False):
        return None
    if not data.get("organ"):
        return None

    return Finding(
        name=data["organ"],
        organ=data.get("organ"),
        location=data.get("location"),
        side=data.get("side"),
        size_mm=data.get("size_mm"),
        description=data.get("description", sentence.strip()),
        certainty="LOW",  # AI-assisted extraction is always LOW by default
        status="ACTIVE",
    )


def parse(
    dictation_text: str,
    call_claude=None,
    organ_hints: Optional[List[str]] = None,
) -> List[Finding]:
    """
    Main entry point. Splits dictation into sentences, applies rules
    first, and falls back to AI extraction (if `call_claude` is
    provided) only for sentences that look clinical but didn't match
    a rule.

    `organ_hints`: list of organ/region names this parser should
    recognize. Callers should normally pass the
    `expected_organs_or_regions` list from the relevant template's
    JSON definition (template_engine.load_template(template_id)
    ["expected_organs_or_regions"]), so the parser uses the correct
    vocabulary for the study type being dictated — e.g. liver/spleen
    terms for an abdominal ultrasound, vertebral terms for a spine
    MRI, etc. If not provided, falls back to a minimal default
    vocabulary (brain CT terms only) for backward compatibility.

    `call_claude` is optional and injected by the caller so this
    module has no hard dependency on a specific API client. If it is
    None, sentences that need the AI fallback are simply skipped
    (never guessed).
    """
    hints = organ_hints if organ_hints is not None else _DEFAULT_ORGAN_HINTS

    findings: List[Finding] = []

    sentences = [s.strip() for s in re.split(r"(?<=[.;])\s+", dictation_text) if s.strip()]

    for sentence in sentences:
        finding = _extract_with_rules(sentence, hints)

        if finding is None and _looks_clinical(sentence, hints) and call_claude is not None:
            finding = _extract_with_ai(sentence, call_claude)

        if finding is not None:
            findings.append(finding)

    return findings
