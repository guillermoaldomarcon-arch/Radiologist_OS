"""
confidence.py

Defines the Confidence enum used across Radiologist_OS to express the
model's calibrated certainty about a Finding, Report, or any other
clinically relevant object.

Design principle (per project philosophy):
"Never increase certainty." This enum exists to make uncertainty explicit
and machine-readable, never to inflate it.
"""

from enum import Enum


class Confidence(Enum):
    """
    Calibrated confidence level.

    LOW:      Finding is possible but not well supported by the available
              evidence/text. Should generally trigger review.
    MODERATE: Default level. Reasonable support, but not definitive.
    HIGH:     Strong, unambiguous support in the source text/evidence.
    """

    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"

    def __str__(self) -> str:
        return self.value
