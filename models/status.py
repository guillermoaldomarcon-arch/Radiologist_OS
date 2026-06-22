"""
status.py

Defines the Status enum used across Radiologist_OS to express the
longitudinal/clinical state of a Finding or Report.

Design principle (per project philosophy):
Status reflects what the evidence supports, never what the system
assumes. FLAGGED exists specifically to support the Quality Engine's
"never auto-correct, never auto-release" rule: a Finding/Report that
is FLAGGED must be reviewed by the radiologist before release.
"""

from enum import Enum


class Status(Enum):
    """
    Clinical/workflow status of a Finding or Report.

    ACTIVE:      Currently present, no prior comparison available yet.
    STABLE:      Present and unchanged compared to prior study.
    NEW:         Not present in the prior study, newly identified.
    RESOLVED:    Was present in a prior study, no longer present.
    CHRONIC:     Long-standing, consistently present across studies.
    PROGRESSIVE: Present and worsening/growing compared to prior study.
    FLAGGED:     Quality Engine detected a possible issue (structural
                 inconsistency or unsupported claim). Blocks automatic
                 release until reviewed by the radiologist. Never set
                 by the system as a final state — always requires
                 human resolution.
    """

    ACTIVE = "ACTIVE"
    STABLE = "STABLE"
    NEW = "NEW"
    RESOLVED = "RESOLVED"
    CHRONIC = "CHRONIC"
    PROGRESSIVE = "PROGRESSIVE"
    FLAGGED = "FLAGGED"
