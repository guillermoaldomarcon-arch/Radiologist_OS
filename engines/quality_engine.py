"""
quality_engine.py

Detects structural errors and possible hallucinations in a list of
Finding objects. NEVER corrects anything automatically.

Design principle (per project philosophy):
"Never liberate a critical error automatically." This engine's only
output is information: which findings are flagged, and why. The
decision to fix, dismiss, or accept a flag always belongs to the
radiologist.

Three layers, each only runs if the previous one did not already
flag the finding:

Layer 1 — Structural validation (deterministic, no AI calls)
    - Laterality contradiction within the same finding (side field
      vs. a different laterality term appearing in description).
    - organ not present in the template's expected_organs_or_regions.
    - Duplicate finding (same organ + side + description) within the
      same report.

Layer 2 — Clinical coherence validation (second Claude call, closed
question only)
    - Only runs if Layer 1 did not flag the finding.
    - Asks Claude a closed, specific question: is this finding
      supported by the original dictated text, or does it contain a
      measurement/laterality/claim that is NOT present in the source?
    - Like the Parser Engine's AI fallback, this is injected via a
      `call_claude` function so the module has no hard dependency on
      a specific API client and stays testable.

Layer 3 — Blocking, not auto-correction
    - Any finding flagged by Layer 1 or Layer 2 gets status="FLAGGED"
      and a recorded reason.
    - This engine NEVER modifies size_mm, side, organ, or description
      to "fix" a detected problem. It only flags.
"""

import json
from typing import Callable, List, Optional

from finding import Finding


_LATERALITY_TERMS = ["derecho", "derecha", "izquierdo", "izquierda", "bilateral"]

_ACCENT_MAP = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")


def _strip_accents(text: str) -> str:
    """Same utility every other engine in this project uses -- kept
    consistent rather than reinventing accent handling here."""
    return text.translate(_ACCENT_MAP)


class QualityIssue:
    """
    A single detected issue for a specific Finding. Informational
    only — does not itself modify the Finding beyond the status flag
    applied in Layer 3.
    """

    def __init__(self, finding: Finding, reason: str, layer: int):
        self.finding = finding
        self.reason = reason
        self.layer = layer

    def __repr__(self) -> str:
        return f"QualityIssue(finding={self.finding.name!r}, layer={self.layer}, reason={self.reason!r})"


# ---------------------------------------------------------------------------
# Layer 1 — Structural validation
# ---------------------------------------------------------------------------

def _check_laterality_contradiction(finding: Finding) -> Optional[str]:
    """
    Flags a finding if its `side` field disagrees with a different
    laterality term mentioned in its own description.

    Example of a contradiction: side="derecho" but description
    contains "izquierdo".
    """
    if not finding.side or not finding.description:
        return None

    description_lower = finding.description.lower()
    side_lower = finding.side.lower()

    mentioned_terms = [t for t in _LATERALITY_TERMS if t in description_lower]

    # "bilateral" mentioned alongside a one-sided `side` value is a
    # contradiction worth flagging — it's ambiguous which is correct.
    contradicting_terms = [
        t for t in mentioned_terms
        if t != side_lower and not (t == "bilateral" and side_lower == "bilateral")
    ]

    if contradicting_terms:
        return (
            f"Lateralidad contradictoria: side='{finding.side}' pero la "
            f"descripción menciona '{', '.join(contradicting_terms)}'."
        )
    return None


def _check_organ_not_in_template(
    finding: Finding, expected_organs: List[str]
) -> Optional[str]:
    """
    Flags a finding whose organ doesn't match (even loosely, by
    substring after accent-stripping) any entry in the template's own
    expected_organs_or_regions. Substring match, not exact equality --
    same lesson as devil_advocate_engine.py's classification lookup:
    the AI's organ vocabulary can be compound phrases, and template
    entries can be broader categories (e.g. "riñón" vs "riñones").

    Does NOT run for findings with no organ at all (nothing to check).
    """
    if not finding.organ:
        return None

    organ_norm = _strip_accents(finding.organ.lower().strip())
    expected_norm = [_strip_accents(o.lower().strip()) for o in expected_organs]

    if any(organ_norm in e or e in organ_norm for e in expected_norm):
        return None

    return (
        f"Órgano '{finding.organ}' no está en la lista de órganos/regiones "
        f"esperados de esta plantilla -- posible error de extracción o "
        f"plantilla incorrecta para este estudio."
    )


def _check_duplicates(findings: List[Finding]) -> dict:
    """
    Returns {finding_index: reason} for findings that are exact
    duplicates (same organ + side + description, accent/case-
    insensitive) of an earlier finding in the same list.

    Only the LATER occurrence is flagged — the first one stands
    untouched. Consistent with "never silently discard": a duplicate
    is flagged for the radiologist to resolve (confirm it's really
    two separate findings, or that one is a parsing artifact), never
    merged or dropped automatically by this engine.
    """
    seen: dict = {}
    duplicates: dict = {}

    for i, f in enumerate(findings):
        key = (
            _strip_accents((f.organ or "").lower().strip()),
            _strip_accents((f.side or "").lower().strip()),
            _strip_accents((f.description or "").lower().strip()),
        )
        if key in seen:
            duplicates[i] = (
                f"Hallazgo duplicado del ya reportado como "
                f"'{findings[seen[key]].name}' (mismo órgano/lado/descripción)."
            )
        else:
            seen[key] = i

    return duplicates


def check_layer1(
    findings: List[Finding], expected_organs: List[str]
) -> List[QualityIssue]:
    """
    Runs all Layer 1 checks. Only ACTIVE findings are checked --
    NO_FINDING and FLAGGED findings have nothing structural to verify
    here (FLAGGED findings were already flagged upstream, e.g. by
    Parser Engine's negation safety-net).

    Per finding, checks stop at the first issue found (laterality,
    then organ, then duplicate) -- one reason is enough to flag; this
    engine's job is to flag, not to enumerate every possible problem
    with a single finding.
    """
    issues: List[QualityIssue] = []
    duplicate_map = _check_duplicates(findings)

    for i, f in enumerate(findings):
        if f.status != "ACTIVE":
            continue

        reason = _check_laterality_contradiction(f)
        if reason:
            issues.append(QualityIssue(f, reason, layer=1))
            continue

        reason = _check_organ_not_in_template(f, expected_organs)
        if reason:
            issues.append(QualityIssue(f, reason, layer=1))
            continue

        if i in duplicate_map:
            issues.append(QualityIssue(f, duplicate_map[i], layer=1))

    return issues


# ---------------------------------------------------------------------------
# Layer 2 — Clinical coherence validation (AI, closed question)
# ---------------------------------------------------------------------------

def _ask_coherence(
    finding: Finding, dictation_text: str, call_claude: Callable[[str], str]
) -> Optional[str]:
    """
    Asks Claude a single closed question about ONE finding: is it
    supported by the original dictated text, or does it contain a
    claim (measurement, laterality, location) not actually present in
    the source. This is independent from Parser Engine's own
    _verify_finding_against_text (a rules-based overlap check) --
    this is a second, AI-driven opinion, run only when Layer 1 found
    nothing structurally wrong.

    A malformed/unparseable AI response never flags the finding --
    absence of a clear "unsupported" verdict is not itself a quality
    issue. This mirrors every other engine's rule: never let a broken
    AI call silently invent a problem (or silently invent a pass).
    """
    prompt = f"""Sos un verificador estricto de coherencia clínica. Te doy UN hallazgo ya extraído de un dictado médico, y el texto original completo del dictado. Tu única tarea es determinar si el hallazgo está respaldado por el texto original, o si contiene algún dato (medida, lateralidad, ubicación o afirmación clínica) que NO está presente en el dictado original.

No evalúes si el hallazgo es clínicamente correcto ni le agregues juicio médico -- solo compará el hallazgo extraído contra el texto fuente, dato por dato.

Hallazgo extraído:
organ={finding.organ!r}, location={finding.location!r}, side={finding.side!r}, size_mm={finding.size_mm}, description={finding.description!r}

Dictado original:
\"\"\"{dictation_text}\"\"\"

Respondé ÚNICAMENTE con un objeto JSON de esta forma exacta, sin texto adicional, sin markdown:

{{"supported": boolean, "unsupported_claim": string or null}}

"supported" es false si y solo si hay un dato del hallazgo que no está respaldado por el dictado original. "unsupported_claim" describe brevemente cuál dato, solo si supported es false; en caso contrario, null."""

    raw_response = call_claude(prompt)

    try:
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.replace("json", "", 1).strip()
        data = json.loads(cleaned)
    except (json.JSONDecodeError, AttributeError):
        return None

    if data.get("supported") is False:
        claim = data.get("unsupported_claim") or "dato no especificado"
        return (
            f"Verificación IA (capa 2): posible dato no respaldado por el "
            f"dictado original ({claim})."
        )
    return None


def check_layer2(
    findings: List[Finding],
    dictation_text: str,
    call_claude: Callable[[str], str],
    skip_indices: Optional[set] = None,
) -> List[QualityIssue]:
    """
    Runs Layer 2 only for ACTIVE findings whose index is not in
    `skip_indices` (i.e., findings Layer 1 already flagged).
    """
    skip_indices = skip_indices or set()
    issues: List[QualityIssue] = []

    for i, f in enumerate(findings):
        if i in skip_indices or f.status != "ACTIVE":
            continue
        reason = _ask_coherence(f, dictation_text, call_claude)
        if reason:
            issues.append(QualityIssue(f, reason, layer=2))

    return issues


# ---------------------------------------------------------------------------
# Layer 3 — Blocking (applies the flag, never touches finding data)
# ---------------------------------------------------------------------------

def review(
    findings: List[Finding],
    expected_organs: List[str],
    dictation_text: str = "",
    call_claude: Optional[Callable[[str], str]] = None,
) -> List[QualityIssue]:
    """
    Entry point. Runs Layer 1 always (deterministic, no AI cost).
    Runs Layer 2 only for findings Layer 1 did not already flag, and
    only if a call_claude function was provided -- Layer 2 is
    optional by design (e.g. offline/no-API testing), matching Parser
    Engine's own fallback pattern.

    IMPORTANT — this function is PURE: it does NOT mutate any
    Finding's status. It only detects and returns issues. Call
    apply_flags() explicitly, and only once every other engine that
    needs to see the finding as still ACTIVE has already run.

    Why the mutation is a separate step: devil_advocate_engine.py's
    Rule F (suggest_impression_level) is explicitly designed to
    receive this module's `quality_issues` list while the flagged
    findings are STILL status=="ACTIVE" -- it cross-references
    quality_issues by finding name against its own `active` list to
    decide whether to show "resolvé los flags antes de cerrar la
    impresión". If this module flipped status to FLAGGED before
    devil_advocate_engine.review() ran, that finding would no longer
    appear in `active` at all, and Rule F would never fire -- silently
    breaking a warning that's specifically meant to reach the
    radiologist. Confirmed by test: the exact failure this ordering
    prevents.
    """
    layer1_issues = check_layer1(findings, expected_organs)
    layer1_flagged_indices = {
        i for i, f in enumerate(findings)
        if any(issue.finding is f for issue in layer1_issues)
    }

    layer2_issues: List[QualityIssue] = []
    if call_claude is not None:
        layer2_issues = check_layer2(
            findings, dictation_text, call_claude, skip_indices=layer1_flagged_indices
        )

    return layer1_issues + layer2_issues


def apply_flags(issues: List[QualityIssue]) -> None:
    """
    Layer 3. Applies status="FLAGGED" to every finding referenced in
    `issues`. This is the ONLY function in this module that mutates
    anything -- size_mm, side, organ, and description are never
    touched by any part of this engine, only this one status field.

    Call this AFTER every engine that needs to see the finding as
    ACTIVE has already run (currently: devil_advocate_engine.review()).
    Engines that run after apply_flags() (differential_engine,
    diagnosis_phrasing_engine) will correctly skip flagged findings,
    since they already filter on status=="ACTIVE" by their own design.
    """
    for issue in issues:
        issue.finding.status = "FLAGGED"
