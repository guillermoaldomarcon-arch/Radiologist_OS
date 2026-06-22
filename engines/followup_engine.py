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


# Combined stability threshold, inspired by RECIST-style reproducibility
# criteria: a measurement difference only counts as a real change if it
# exceeds BOTH an absolute minimum (to avoid flagging measurement noise
# on small lesions) AND a relative minimum (so a large lesion doesn't
# need the same absolute change as a small one to count as progressive).
# Decided with Guille: 3mm absolute (commonly cited inter-observer
# reproducibility figure) AND 20% relative to the prior size.
_STABILITY_THRESHOLD_MM_ABSOLUTE = 3.0
_STABILITY_THRESHOLD_RELATIVE = 0.20


def _is_real_change(previous_size_mm: float, current_size_mm: float) -> bool:
    """
    Returns True only if the change in size exceeds BOTH the absolute
    (mm) and relative (%) thresholds. Either threshold alone passing
    is NOT enough — this avoids over-flagging small lesions for tiny
    absolute changes that are large in percentage terms, and avoids
    under-flagging large lesions for absolute changes that look small
    in percentage terms but are clinically real.
    """
    delta = abs(current_size_mm - previous_size_mm)

    if previous_size_mm == 0:
        # Avoid division by zero; treat any new positive size as a
        # real change if it also clears the absolute threshold.
        return delta >= _STABILITY_THRESHOLD_MM_ABSOLUTE

    relative_change = delta / previous_size_mm

    return (
        delta >= _STABILITY_THRESHOLD_MM_ABSOLUTE
        and relative_change >= _STABILITY_THRESHOLD_RELATIVE
    )


def _same_region(a: Finding, b: Finding) -> bool:
    """
    Two findings are considered "the same region" if organ and
    location both match (case-insensitive). `side` is intentionally
    NOT part of this match — a laterality change between studies for
    the same organ/location is itself something Quality Engine should
    have flagged upstream, not something Followup should silently
    paper over by treating it as a non-match.
    """
    organ_match = (a.organ or "").strip().lower() == (b.organ or "").strip().lower()
    location_match = (a.location or "").strip().lower() == (b.location or "").strip().lower()
    return organ_match and location_match


def _classify_pair(previous: Finding, current: Finding) -> str:
    """
    Classifies a matched pair (same organ/location, found in both the
    previous and current report) into one of:
    STABLE, PROGRESSIVE, RESOLVED, NEW, INDETERMINATE.
    """
    prev_active = previous.status == "ACTIVE"
    curr_active = current.status == "ACTIVE"

    # NO_FINDING -> ACTIVE: genuinely new pathology in a previously
    # normal/evaluated region.
    if not prev_active and curr_active:
        return "NEW"

    # ACTIVE -> NO_FINDING: previously abnormal, now recorded as normal.
    if prev_active and not curr_active:
        return "RESOLVED"

    # Both NO_FINDING: nothing pathological then or now.
    if not prev_active and not curr_active:
        return "STABLE"

    # Both ACTIVE: compare size if both have a measurement.
    if previous.size_mm is not None and current.size_mm is not None:
        if not _is_real_change(previous.size_mm, current.size_mm):
            return "STABLE"

        delta = current.size_mm - previous.size_mm
        if delta > 0:
            return "PROGRESSIVE"
        # Shrinking is still "changed", but the MVP's classification
        # set has no dedicated "improving" category yet (ROADMAP:
        # Digital Twin Engine may refine this). For now, a decrease
        # is reported as INDETERMINATE rather than silently folded
        # into STABLE or labeled with a category that doesn't exist
        # in this enum's MVP scope.
        return "INDETERMINATE"

    # Both ACTIVE but at least one has no measurement to compare —
    # not enough evidence to claim STABLE or PROGRESSIVE.
    return "INDETERMINATE"


def compare_reports(
    previous_report: Optional[Report], current_report: Report
) -> List[dict]:
    """
    Compares current_report's findings against previous_report's
    findings (if any) and returns a list of classification results,
    one per current finding:

        {
            "finding": Finding,       # the CURRENT finding
            "classification": str,    # NEW / STABLE / PROGRESSIVE /
                                       # RESOLVED / INDETERMINATE
            "matched_previous": Finding or None,
        }

    If previous_report is None (no prior study available), every
    current finding is classified as NEW if ACTIVE, or STABLE if
    NO_FINDING — there is no prior evidence to compare against, so we
    do not claim PROGRESSIVE or RESOLVED without a baseline.

    This function does NOT mutate either report. It only reads
    findings and returns classification results; applying those
    results (e.g. setting Finding.status to a longitudinal value) is
    left to the caller, consistent with "never auto-modify without an
    explicit step the radiologist can review."
    """
    results: List[dict] = []

    if previous_report is None:
        for current in current_report.findings:
            classification = "NEW" if current.status == "ACTIVE" else "STABLE"
            results.append(
                {
                    "finding": current,
                    "classification": classification,
                    "matched_previous": None,
                }
            )
        return results

    previous_findings = list(previous_report.findings)

    for current in current_report.findings:
        match = next(
            (p for p in previous_findings if _same_region(p, current)), None
        )

        if match is None:
            # No prior record of this organ/location at all — distinct
            # from NO_FINDING (which means it WAS evaluated and was
            # normal). An unmatched current finding is genuinely new
            # information, but we mark it INDETERMINATE if it's a
            # NO_FINDING entry (no point calling a normal-region
            # report "NEW") and NEW if it's an actual finding.
            classification = "NEW" if current.status == "ACTIVE" else "INDETERMINATE"
        else:
            classification = _classify_pair(match, current)

        results.append(
            {
                "finding": current,
                "classification": classification,
                "matched_previous": match,
            }
        )

    return results
