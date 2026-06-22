"""
recommendation.py

Defines the Recommendation object: a follow-up action suggested as a
result of one or more Finding objects (e.g. "follow-up in 3 months",
"correlate with prior chest X-ray", "urgent clinical correlation
recommended").

Design principle (per project philosophy):
A Recommendation is never a diagnosis and never replaces clinical
judgment. It is always traceable back to the Finding(s) that
generated it, so the radiologist can verify why it was suggested.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Recommendation:
    """
    A single follow-up recommendation tied to one or more findings.

    text:
        The recommendation itself, in plain language
        (e.g. "Seguimiento con TC en 3 meses").

    related_finding_names:
        Names of the Finding objects that generated this
        recommendation. Used for traceability — every recommendation
        must be explainable in terms of the findings that triggered it.

    urgency:
        Independent from the Finding's `certainty`/Confidence. A
        recommendation can be urgent even when confidence in the
        underlying finding is LOW, precisely to avoid losing a
        potentially serious case to uncertainty.
        Expected values: "ROUTINE", "PRIORITY", "URGENT".

    rationale:
        Optional short explanation of why this recommendation was
        generated (e.g. clinical guideline reference, pattern
        recognized). Never invented — left None if there is no
        explicit basis.
    """

    text: str
    related_finding_names: List[str] = field(default_factory=list)
    urgency: str = "ROUTINE"
    rationale: Optional[str] = None
