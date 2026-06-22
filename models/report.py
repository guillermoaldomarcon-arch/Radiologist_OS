"""
report.py

Defines the Report object: the final structured output of the MVP
pipeline (Parser -> Template -> Quality -> Followup -> Report).

Design principle (per project philosophy):
A Report's release status is NEVER set manually by another engine.
It is always derived from the state of its findings. If any Finding
is FLAGGED, the report is automatically blocked from release — this
is the code-level guarantee behind "never auto-release a critical
error."
"""

from dataclasses import dataclass, field
from typing import List, Optional

from confidence import Confidence
from status import Status
from recommendation import Recommendation
from finding import Finding


@dataclass
class Report:
    """
    Final structured radiology report.

    indication:
        Why the study was performed (clinical indication).

    technique:
        How the study was performed (modality, protocol, contrast, etc.).

    findings:
        List of Finding objects produced by the Parser Engine and
        validated by the Quality Engine.

    impression:
        Summary interpretation. In the MVP, this is assembled from
        findings by the Template Engine — never invented beyond what
        the findings support.

    recommendations:
        List of Recommendation objects, each traceable to specific
        findings.

    warnings:
        Populated by the Quality Engine. Plain-language list of
        reasons why one or more findings were FLAGGED. Empty if no
        issues were detected.

    quality_score:
        Optional numeric/qualitative indicator from the Quality
        Engine. Left as Optional[float] for the MVP; not invented if
        the Quality Engine has no basis to produce one.

    confidence:
        Overall Confidence for the report. In the MVP, this should be
        derived as the minimum (most conservative) Confidence across
        all findings — never higher than the least certain finding.

    template_id:
        Identifier of the JSON template definition used to generate
        this report (e.g. "tc_cerebro", "rx_torax"). Required for
        traceability back to the Template Engine.

    status:
        NOT set directly. Use `recompute_status()` after building or
        modifying `findings`. Defaults to a safe, non-releasable state
        until explicitly computed.
    """

    indication: str
    technique: str
    findings: List[Finding] = field(default_factory=list)
    impression: str = ""
    recommendations: List[Recommendation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    quality_score: Optional[float] = None
    confidence: Confidence = Confidence.MODERATE
    template_id: Optional[str] = None
    status: Status = Status.FLAGGED  # safe default: not releasable until computed

    def recompute_status(self) -> Status:
        """
        Derives the report's status from its findings.

        Rule: if ANY finding has status FLAGGED, the report itself
        becomes FLAGGED (not releasable) and a warning is recorded.
        This method never clears a FLAGGED finding automatically —
        it only reads finding state, it never modifies it.
        """
        flagged = [f for f in self.findings if f.status == "FLAGGED"]

        if flagged:
            self.status = Status.FLAGGED
            for f in flagged:
                warning_text = f"Finding '{f.name}' flagged for review."
                if warning_text not in self.warnings:
                    self.warnings.append(warning_text)
        else:
            # No flags: default to ACTIVE. Followup Engine may later
            # refine this per-finding, but the report-level status
            # only needs to express "safe to consider for release".
            self.status = Status.ACTIVE

        return self.status

    def is_releasable(self) -> bool:
        """
        A report is releasable only if its status is not FLAGGED.
        This is the single source of truth other code should check
        before allowing a report to go out — never inspect `findings`
        directly to decide releasability.
        """
        return self.status != Status.FLAGGED
