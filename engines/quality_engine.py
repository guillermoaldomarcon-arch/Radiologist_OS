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


class QualityIssue:
    """
    A single detected issue for a specific Finding. Informational
    only — does not itself modify the Finding.
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
            f"descripción menciona
