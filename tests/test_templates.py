"""
test_templates.py

One end-to-end test per MVP template: dictation text -> Parser ->
Template Engine -> Report. Confirms the pipeline produces sensible,
non-fabricated output for each of the 4 study types.

Each test loads its template's `expected_organs_or_regions` first and
passes that vocabulary to the parser. This is the fix for the issue
found while building these tests: the parser used to rely on a single
hardcoded organ vocabulary (brain-CT specific), so it silently
extracted 0 findings for rx_torax / rm_columna / eco_abdominal. Now
the vocabulary always comes from the active template, so each study
type is recognized using its own anatomy.

These dictations are GENERIC/INVENTED examples for testing the
mechanism only — they are not real patient data and should be
replaced or supplemented with Guille's real (anonymized) dictation
patterns when available, per the MVP plan in
docs/Radiologist_OS_v0.2_MVP.md.

Run with: python3 tests/test_templates.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "models"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engines"))

from parser_engine import parse
from template_engine import build_report, load_template


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


def test_tc_cerebro():
    print("\n[1/4] TC Cerebro")
    dictado = """
Técnica: TC de cerebro sin contraste, cortes axiales.
Parénquima cerebral con hipodensidad de 15 mm a nivel de la región frontal derecha.
Ventrículos de tamaño y morfología conservados.
Cisterna basal sin alteraciones.
Calota sin lesiones óseas evidentes.
"""
    template = load_template("tc_cerebro")
    findings = parse(
        dictado, call_claude=None, organ_hints=template["expected_organs_or_regions"]
    )
    report = build_report(
        findings=findings,
        template_id="tc_cerebro",
        indication="Cefalea de reciente comienzo.",
    )

    _check("se extrajo al menos 1 finding", len(findings) >= 1)
    _check(
        "hay un finding ACTIVE (hallazgo positivo) de parénquima",
        any(f.organ == "parénquima" and f.status == "ACTIVE" for f in findings),
    )
    _check(
        "ventrículos quedó como NO_FINDING (no como hallazgo positivo)",
        any(f.organ == "ventrículo" and f.status == "NO_FINDING" for f in findings),
    )
    _check(
        "la impresión menciona el hallazgo positivo, no las negaciones",
        "hipodensidad" in report.impression.lower()
        and "cisterna" not in report.impression.lower(),
    )


def test_rx_torax():
    print("\n[2/4] Rx Tórax")
    dictado = """
Técnica: Radiografía de tórax frente.
Campos pulmonares sin imágenes de condensación.
Silueta cardíaca de tamaño y morfología conservados.
Senos costofrénicos libres.
"""
    template = load_template("rx_torax")
    findings = parse(
        dictado, call_claude=None, organ_hints=template["expected_organs_or_regions"]
    )
    report = build_report(
        findings=findings,
        template_id="rx_torax",
        indication="Control preoperatorio.",
    )

    _check("se extrajo al menos 1 finding", len(findings) >= 1)
    _check(
        "campos pulmonares quedó como NO_FINDING",
        any(f.organ == "campos pulmonares" and f.status == "NO_FINDING" for f in findings),
    )
    _check(
        "silueta cardíaca quedó como NO_FINDING",
        any(f.organ == "silueta cardíaca" and f.status == "NO_FINDING" for f in findings),
    )


def test_rm_columna():
    print("\n[3/4] RM Columna")
    dictado = """
Técnica: RM de columna, secuencias multiplanares, sin contraste.
Disco intervertebral con protrusión de 6 mm en su componente derecho.
Canal raquídeo de calibre conservado.
Médula espinal sin alteraciones de señal.
"""
    template = load_template("rm_columna")
    findings = parse(
        dictado, call_claude=None, organ_hints=template["expected_organs_or_regions"]
    )
    report = build_report(
        findings=findings,
        template_id="rm_columna",
        indication="Lumbalgia crónica.",
    )

    _check("se extrajo al menos 1 finding", len(findings) >= 1)
    _check(
        "hay un finding ACTIVE de disco intervertebral con medida y lateralidad",
        any(
            f.organ == "disco intervertebral"
            and f.status == "ACTIVE"
            and f.size_mm == 6.0
            for f in findings
        ),
    )
    _check(
        "canal raquídeo quedó como NO_FINDING",
        any(f.organ == "canal raquídeo" and f.status == "NO_FINDING" for f in findings),
    )


def test_eco_abdominal():
    print("\n[4/4] Eco Abdominal")
    dictado = """
Técnica: Ecografía abdominal en tiempo real, modo B.
Hígado de tamaño y ecogenicidad conservados.
Vesícula biliar sin litiasis.
Vía biliar de calibre conservado.
"""
    template = load_template("eco_abdominal")
    findings = parse(
        dictado, call_claude=None, organ_hints=template["expected_organs_or_regions"]
    )
    report = build_report(
        findings=findings,
        template_id="eco_abdominal",
        indication="Dolor abdominal a estudiar.",
    )

    _check("se extrajo al menos 1 finding", len(findings) >= 1)
    _check(
        "hígado quedó como NO_FINDING",
        any(f.organ == "hígado" and f.status == "NO_FINDING" for f in findings),
    )
    _check(
        "vesícula biliar quedó como NO_FINDING",
        any(f.organ == "vesícula biliar" and f.status == "NO_FINDING" for f in findings),
    )


if __name__ == "__main__":
    print("=" * 70)
    print("TEST: un caso por template (MVP)")
    print("=" * 70)

    test_tc_cerebro()
    test_rx_torax()
    test_rm_columna()
    test_eco_abdominal()

    print("\n" + "=" * 70)
    print(f"RESULTADO: {_PASS_COUNT} PASS, {_FAIL_COUNT} FAIL")
    print("=" * 70)

    if _FAIL_COUNT > 0:
        sys.exit(1)
