"""
test_main_followup.py

Integration test for the /report endpoint's optional
previous_dictation_text field. Confirms the followup comparison is
wired end-to-end through the real FastAPI app defined in
backend/main.py.

call_claude is monkeypatched to a prompt-aware fake (see
_fake_call_claude below) rather than None: parser_engine.py v2 treats
the AI as PRIMARY, so call_claude=None would only exercise its
deprecated rules-only fallback, not the real production path. This
means the test never calls the real Anthropic API and never needs
ANTHROPIC_API_KEY, so it runs the same way locally and in CI.

Run with: python3 tests/test_main_followup.py
"""

import sys
import os
import re
import json
import importlib.util

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_REPO_ROOT, "models"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "engines"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "integrations"))
sys.path.insert(0, _REPO_ROOT)

# Loaded by file path (not "import main") to avoid any ambiguity with
# the placeholder main.py at the repo root -- this always loads
# backend/main.py specifically, regardless of what else is on sys.path.
_main_spec = importlib.util.spec_from_file_location(
    "backend_main", os.path.join(_REPO_ROOT, "backend", "main.py")
)
backend_main = importlib.util.module_from_spec(_main_spec)
_main_spec.loader.exec_module(backend_main)

import parser_engine
from template_engine import load_template as _load_template

_TC_CEREBRO_HINTS = _load_template("tc_cerebro")["expected_organs_or_regions"]


# Monkeypatch: replace the real Anthropic call with a deterministic
# fake that inspects each prompt and answers in the exact JSON shape
# each caller expects. parser_engine.py v2 treats the AI as PRIMARY
# (call_claude=None only exercises its legacy rules-only fallback --
# see parser_engine.py's own module docstring), so a production-like
# test of /report cannot use call_claude=None: it would silently test
# a deprecated code path instead of what actually runs. For the
# extraction prompt specifically, this fake reuses parser_engine's own
# _extract_with_rules_only() per sentence -- the same deterministic
# logic already covered by test_templates.py -- so the fake AI's
# answer is a faithful stand-in without ever calling the real API.
def _fake_call_claude(prompt: str) -> str:
    if "PARTE 1 -- MATCHING" in prompt:
        # line_based_report_engine's finding-to-template-line matching.
        # Empty match is a valid, already-handled shape (everything
        # lands in "unmatched_findings"); it doesn't affect `findings`
        # itself, which is what the followup comparison runs on.
        return '{"matches": [], "composed_lines": [], "unmatched_finding_indices": []}'

    if "verificador estricto de coherencia" in prompt:
        # quality_engine.py Layer 2 coherence check.
        return '{"supported": true, "reason": null}'

    if "extrae hallazgos radiológicos" in prompt:
        # parser_engine.py's primary AI extraction prompt.
        match = re.search(r'Dictado:\n"""(.*)"""', prompt, re.DOTALL)
        dictation_text = match.group(1) if match else ""
        sentences = [
            s.strip() for s in re.split(r"(?<=[.;])\s+", dictation_text) if s.strip()
        ]
        raw = []
        for sentence in sentences:
            f = parser_engine._extract_with_rules_only(sentence, _TC_CEREBRO_HINTS)
            if f is not None:
                raw.append({
                    "organ": f.organ,
                    "location": f.location,
                    "side": f.side,
                    "size_mm": f.size_mm,
                    "description": f.description,
                    "is_pathological": f.status == "ACTIVE",
                })
        return json.dumps(raw, ensure_ascii=False)

    return "{}"


backend_main._get_call_claude = lambda: (_fake_call_claude, Exception)

from fastapi.testclient import TestClient

client = TestClient(backend_main.app)

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


def test_report_without_previous_dictation_has_empty_followup():
    print("\n[1/3] Sin previous_dictation_text: comportamiento sin cambios")

    payload = {
        "template_id": "tc_cerebro",
        "dictation_text": (
            "Parenquima cerebral con hipodensidad de 15 mm a nivel de "
            "la region frontal derecha. Ventriculos de tamano y "
            "morfologia conservados. Cisterna basal sin alteraciones. "
            "Calota sin lesiones oseas evidentes."
        ),
        "indication": "Cefalea de reciente comienzo.",
    }

    response = client.post("/report", json=payload)
    _check("status code 200", response.status_code == 200, f"(obtuvo {response.status_code})")

    body = response.json()
    _check(
        "followup queda vacio cuando no se manda previous_dictation_text",
        body.get("followup") == [],
        f"(obtuvo {body.get('followup')})",
    )


def test_report_with_previous_dictation_detects_progressive_change():
    print("\n[2/3] Con previous_dictation_text: cambio real se clasifica PROGRESSIVE")

    payload = {
        "template_id": "tc_cerebro",
        "dictation_text": (
            "Parenquima cerebral con hipodensidad de 15 mm a nivel de "
            "la region frontal derecha. Ventriculos de tamano y "
            "morfologia conservados. Cisterna basal sin alteraciones. "
            "Calota sin lesiones oseas evidentes."
        ),
        "previous_dictation_text": (
            "Parenquima cerebral con hipodensidad de 10 mm a nivel de "
            "la region frontal derecha."
        ),
        "indication": "Control evolutivo.",
    }

    response = client.post("/report", json=payload)
    _check("status code 200", response.status_code == 200, f"(obtuvo {response.status_code})")

    body = response.json()
    followup = body.get("followup", [])
    _check("se devolvio al menos 1 resultado de followup", len(followup) >= 1, f"(obtuvo {followup})")

    parenquima_result = next((r for r in followup if r.get("organ") == "parénquima"), None)
    _check("hay un resultado para 'parénquima'", parenquima_result is not None)
    if parenquima_result is not None:
        _check(
            "parénquima (10mm->15mm) se clasifico PROGRESSIVE",
            parenquima_result.get("classification") == "PROGRESSIVE",
            f"(obtuvo {parenquima_result.get('classification')})",
        )
        _check(
            "matched_previous_description quedo seteado (no None)",
            parenquima_result.get("matched_previous_description") is not None,
        )


def test_report_with_blank_previous_dictation_is_ignored():
    print("\n[3/3] previous_dictation_text en blanco se ignora (equivale a no mandarlo)")

    payload = {
        "template_id": "tc_cerebro",
        "dictation_text": (
            "Parenquima cerebral con hipodensidad de 15 mm a nivel de "
            "la region frontal derecha."
        ),
        "previous_dictation_text": "   ",
        "indication": "Control.",
    }

    response = client.post("/report", json=payload)
    _check("status code 200", response.status_code == 200, f"(obtuvo {response.status_code})")

    body = response.json()
    _check(
        "followup queda vacio cuando previous_dictation_text es solo espacios",
        body.get("followup") == [],
        f"(obtuvo {body.get('followup')})",
    )


if __name__ == "__main__":
    print("=" * 70)
    print("TEST: /report -- comparacion evolutiva (previous_dictation_text)")
    print("=" * 70)

    test_report_without_previous_dictation_has_empty_followup()
    test_report_with_previous_dictation_detects_progressive_change()
    test_report_with_blank_previous_dictation_is_ignored()

    print("\n" + "=" * 70)
    print(f"RESULTADO: {_PASS_COUNT} PASS, {_FAIL_COUNT} FAIL")
    print("=" * 70)

    if _FAIL_COUNT > 0:
        sys.exit(1)
