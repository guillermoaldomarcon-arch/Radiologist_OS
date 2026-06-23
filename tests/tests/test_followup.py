"""
test_followup.py

End-to-end test for the Followup Engine: builds a "previous" Report
and a "current" Report for the same simulated patient (same template)
and confirms compare_reports() classifies each finding correctly:

  - PROGRESSIVE: a lesion that grew beyond the combined threshold
    (>=3mm AND >=20% relative to its prior size).
  - NEW: a region that was NO_FINDING (normal) in the prior study and
    is now ACTIVE (a new finding) — this depends on the
    Parser/Quality Engines' NO_FINDING tracking, not just comparing
    positive findings to positive findings.
  - STABLE: a region that stayed NO_FINDING in both studies.
  - The no-prior-study case: every ACTIVE finding becomes NEW and
    every NO_FINDING finding becomes STABLE, since there is no
    baseline to claim PROGRESSIVE/RESOLVED against.

Run with: python3 tests/test_followup.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "models"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engines"))

from finding import Finding
from report import Report
from followup_engine import compare_reports


_PASS_COUNT = 0
_FAIL_COUNT = 0


def _check(label: str, condition: bool, detail: str = ""):
    global _PASS_COUNT, _FAIL_COUNT
    if condition:
        _PASS_COUNT += 1
        print(f"  PASS: {label}")
    else:
        _FAIL_COUNT += 1
        print(f"  FAIL: {label} {detail}")


def test_followup_with_prior_study():
    print("\n[1/2] Comparación contra estudio previo")

    previo = Report(
        indication="Control",
        technique="TC de cerebro sin contraste.",
        findings=[
            Finding(
                name="parénquima", organ="parénquima", location="frontal",
                side="derecho", size_mm=10.0,
                description="Hipodensidad de 10mm en frontal derecho.",
                certainty="HIGH", status="ACTIVE",
            ),
            Finding(
                name="cisterna", organ="cisterna", location="basal",
                side=None, size_mm=None,
                description="Cisterna basal sin alteraciones.",
                certainty="HIGH", status="NO_FINDING",
            ),
            Finding(
                name="calota", organ="calota", location=None,
                side=None, size_mm=None,
                description="Calota sin lesiones óseas.",
                certainty="HIGH", status="NO_FINDING",
            ),
        ],
    )

    actual = Report(
        indication="Control evolutivo",
        technique="TC de cerebro sin contraste.",
        findings=[
            # 10mm -> 14mm: delta=4mm (>=3mm) y 40% (>=20%) -> PROGRESSIVE
            Finding(
                name="parénquima", organ="parénquima", location="frontal",
                side="derecho", size_mm=14.0,
                description="Hipodensidad de 14mm en frontal derecho.",
                certainty="HIGH", status="ACTIVE",
            ),
            # NO_FINDING -> ACTIVE: NEW
            Finding(
                name="cisterna", organ="cisterna", location="basal",
                side=None, size_mm=None,
                description="Cisterna basal con leve asimetría.",
                certainty="MODERATE", status="ACTIVE",
            ),
            # NO_FINDING -> NO_FINDING: STABLE
            Finding(
                name="calota", organ="calota", location=None,
                side=None, size_mm=None,
                description="Calota sin lesiones óseas.",
                certainty="HIGH", status="NO_FINDING",
            ),
        ],
    )

    results = compare_reports(previo, actual)
    by_organ = {r["finding"].organ: r["classification"] for r in results}

    _check(
        "parénquima (10mm->14mm, cambio real) clasificado PROGRESSIVE",
        by_organ.get("parénquima") == "PROGRESSIVE",
        f"(obtuvo {by_organ.get('parénquima')})",
    )
    _check(
        "cisterna (NO_FINDING->ACTIVE) clasificada NEW",
        by_organ.get("cisterna") == "NEW",
        f"(obtuvo {by_organ.get('cisterna')})",
    )
    _check(
        "calota (NO_FINDING->NO_FINDING) clasificada STABLE",
        by_organ.get("calota") == "STABLE",
        f"(obtuvo {by_organ.get('calota')})",
    )


def test_followup_without_prior_study():
    print("\n[2/2] Sin estudio previo disponible (paciente nuevo)")

    actual = Report(
        indication="Primer estudio",
        technique="TC de cerebro sin contraste.",
        findings=[
            Finding(
                name="parénquima", organ="parénquima", location="frontal",
                side="derecho", size_mm=10.0,
                description="Hipodensidad de 10mm.",
                certainty="HIGH", status="ACTIVE",
            ),
            Finding(
                name="calota", organ="calota", location=None,
                side=None, size_mm=None,
                description="Calota sin lesiones óseas.",
                certainty="HIGH", status="NO_FINDING",
            ),
        ],
    )

    results = compare_reports(previous_report=None, current_report=actual)
    by_organ = {r["finding"].organ: r["classification"] for r in results}

    _check(
        "sin historial, hallazgo positivo se clasifica NEW (no PROGRESSIVE/RESOLVED sin base)",
        by_organ.get("parénquima") == "NEW",
        f"(obtuvo {by_organ.get('parénquima')})",
    )
    _check(
        "sin historial, región normal se clasifica STABLE",
        by_organ.get("calota") == "STABLE",
        f"(obtuvo {by_organ.get('calota')})",
    )


if __name__ == "__main__":
    print("=" * 70)
    print("TEST: Followup Engine — comparación longitudinal")
    print("=" * 70)

    test_followup_with_prior_study()
    test_followup_without_prior_study()

    print("\n" + "=" * 70)
    print(f"RESULTADO: {_PASS_COUNT} PASS, {_FAIL_COUNT} FAIL")
    print("=" * 70)

    if _FAIL_COUNT > 0:
        sys.exit(1)
