"""
test_quality_adversarial.py

Adversarial test for the Quality Engine: deliberately constructs
Finding objects that contain fabricated data (a laterality
contradiction, an organ that doesn't belong to the active template,
and — via a simulated AI call — a measurement that isn't supported by
the original dictated text) and confirms the Quality Engine:

  1. Detects each problem.
  2. Flags the finding (status -> "FLAGGED").
  3. Does NOT modify/correct any of the original data (organ, side,
     size_mm, description stay exactly as they were).

This directly tests the project's core safety principle: "never
liberate a critical error automatically."

Run with: python3 tests/test_quality_adversarial.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "models"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engines"))

from finding import Finding
from quality_engine import apply_quality_check
from template_engine import load_template


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


def test_laterality_contradiction_is_flagged_not_corrected():
    print("\n[1/3] Contradicción de lateralidad")

    template = load_template("tc_cerebro")

    # side dice "derecho" pero la descripción dice "izquierda" — esto
    # nunca debería pasar inadvertido.
    f = Finding(
        name="parénquima",
        organ="parénquima",
        side="derecho",
        size_mm=12.0,
        description="Hipodensidad de 12 mm en parénquima frontal izquierda.",
        certainty="HIGH",
        status="ACTIVE",
    )

    original_side = f.side
    original_size = f.size_mm
    original_description = f.description

    issues = apply_quality_check(
        [f], expected_organs_or_regions=template["expected_organs_or_regions"]
    )

    _check("se detectó al menos 1 issue", len(issues) >= 1)
    _check("el finding quedó FLAGGED", f.status == "FLAGGED")
    _check(
        "el motor NO corrigió side (sigue siendo 'derecho', no se cambió a 'izquierdo')",
        f.side == original_side,
    )
    _check("el motor NO modificó size_mm", f.size_mm == original_size)
    _check("el motor NO modificó description", f.description == original_description)


def test_organ_not_in_template_is_flagged():
    print("\n[2/3] Organ que no pertenece al template")

    template = load_template("tc_cerebro")

    # "bazo" no es una región cerebral — esto simula un error de
    # transcripción o un cruce de contenido entre estudios distintos.
    f = Finding(
        name="bazo",
        organ="bazo",
        side=None,
        size_mm=None,
        description="Bazo de tamaño normal.",
        certainty="MODERATE",
        status="NO_FINDING",
    )

    issues = apply_quality_check(
        [f], expected_organs_or_regions=template["expected_organs_or_regions"]
    )

    _check("se detectó al menos 1 issue", len(issues) >= 1)
    _check("el finding quedó FLAGGED", f.status == "FLAGGED")
    _check("el motor NO modificó organ", f.organ == "bazo")


def test_fabricated_measurement_caught_by_layer_2():
    print("\n[3/3] Medida inventada, detectada solo por Capa 2 (coherencia con IA)")

    template = load_template("tc_cerebro")

    original_text = (
        "Parénquima cerebral con hipodensidad inespecífica en región "
        "frontal derecha, sin medida precisa reportada."
    )

    # Este finding pasa la Capa 1 sin problemas (organ válido, sin
    # contradicción de lateralidad) pero tiene una medida de 15mm que
    # el texto original NO menciona — solo la Capa 2 puede atraparlo.
    f = Finding(
        name="parénquima",
        organ="parénquima",
        side="derecho",
        size_mm=15.0,
        description="Hipodensidad de 15 mm en parénquima frontal derecho.",
        certainty="LOW",
        status="ACTIVE",
    )

    def fake_claude_layer2(prompt: str) -> str:
        return (
            '{"supported": false, "reason": '
            '"El texto original no menciona una medida de 15 mm; '
            'el dictado dice que no hay medida precisa reportada."}'
        )

    original_size = f.size_mm

    issues = apply_quality_check(
        [f],
        expected_organs_or_regions=template["expected_organs_or_regions"],
        original_text=original_text,
        call_claude=fake_claude_layer2,
    )

    _check("se detectó al menos 1 issue (vía Layer 2)", len(issues) >= 1)
    _check(
        "el issue es de Layer 2, no Layer 1 (la medida inventada no es "
        "detectable estructuralmente)",
        any(issue.layer == 2 for issue in issues),
    )
    _check("el finding quedó FLAGGED", f.status == "FLAGGED")
    _check(
        "el motor NO corrigió ni eliminó la medida inventada — solo la flaggeó",
        f.size_mm == original_size,
    )


if __name__ == "__main__":
    print("=" * 70)
    print("TEST ADVERSARIAL: Quality Engine debe detectar y bloquear, nunca corregir")
    print("=" * 70)

    test_laterality_contradiction_is_flagged_not_corrected()
    test_organ_not_in_template_is_flagged()
    test_fabricated_measurement_caught_by_layer_2()

    print("\n" + "=" * 70)
    print(f"RESULTADO: {_PASS_COUNT} PASS, {_FAIL_COUNT} FAIL")
    print("=" * 70)

    if _FAIL_COUNT > 0:
        sys.exit(1)
