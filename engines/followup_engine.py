"""
followup_engine.py

Compares the current report's findings against the patient's most
recent prior report (same template/study type) and classifies each
finding as NEW, STABLE, PROGRESSIVE, RESOLVED, or INDETERMINATE.

Design principle (per project philosophy):
The patient is compared to himself, not to the population. This
engine never compares against population norms — only against the
patient's own prior study. It never invents a prior finding that
isn't there, and never assumes stability in the absence of evidence
(unmatched findings become INDETERMINATE, not silently STABLE).

MVP scope:
Field-by-field comparison (organ + location + size) against the most
recent prior report only. Full longitudinal history (multiple past
studies, trend analysis) is Digital Twin Engine territory — out of
scope here (see ROADMAP).

Key behavior enabled by the Parser/Quality Engines' organ-level
NO_FINDING tracking: because a normal/evaluated region is recorded as
its own Finding (status="NO_FINDING") rather than omitted, this
engine can detect a transition from NO_FINDING -> ACTIVE for the same
organ as a genuine NEW finding — not just compare positive findings
against positive findings.
"""

from typing import List, Optional

from finding import Finding
from report import Report


# Size difference threshold (mm) below which two findings of the same
# organ/location are considered STABLE rather than PROGRESSIVE.
# Deliberately simple and conservative for the MVP — not a clinical
# growth-rate model, just a sanity threshold to avoid calling every
# trivial measurement variation "progressive".
_STABILITY_THRESHOLD_MM = 1.0


def _same_region(a: Finding, b: Finding) -> bool:
    """
    Two findings are considered "the same region" if organ and
    location both match (case-insensitive). `side` is intentionally
    NOT part of this match — a laterality change between studies for
    the same organ/location is itself something Quality Engine should
    have flagged upstream, not
