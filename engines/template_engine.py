"""
template_engine.py

Generic engine that loads a template DEFINITION (JSON, stored under
templates/) and uses it to assemble a structured Report from a list
of Finding objects.

Design principle (per project philosophy):
Templates are DATA, not code. Adding a new study type means adding a
new JSON file under templates/ — never modifying this engine. This
directly supports the "minimum modification principle".

The engine never invents content. If a template expects an
organ/region that has no matching Finding, it is left absent from the
report (not fabricated, not assumed normal) — Quality Engine and the
radiologist remain responsible for noticing gaps.
"""

import json
import os
from typing import List, Optional

from finding import Finding
from report import Report


_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")


class TemplateNotFoundError(Exception):
    """Raised when a template_id has no matching JSON definition."""
    pass


class InvalidTemplateError(Exception):
    """Raised when a template JSON file is malformed or missing required keys."""
    pass


_REQUIRED_TEMPLATE_KEYS = [
    "template_id",
    "modality",
    "study_type",
    "sections",
    "expected_organs_or_regions",
]


def load_template(template_id: str, templates_dir: Optional[str] = None) -> dict:
    """
    Loads and validates a template definition by its template_id.

    Looks for a file named "{template_id}.json" inside templates_dir
    (defaults to the project's templates/ folder).

    Raises TemplateNotFoundError if the file doesn't exist, and
    InvalidTemplateError if it exists but is malformed or missing
    required keys. Never returns a partially-valid template silently.
    """
    directory = templates_dir or _TEMPLATES_DIR
    file_path = os.path.join(directory, f"{template_id}.json")

    if not os.path.isfile(file_path):
        raise TemplateNotFoundError(
            f"No template definition found for '{template_id}' "
            f"(expected {file_path})"
        )

    with open(file_path, "r", encoding="utf-8") as f:
        try:
            definition = json.load(f)
        except json.JSONDecodeError as e:
            raise InvalidTemplateError(
                f"Template '{template_id}' is not valid JSON: {e}"
            )

    missing_keys = [k for k in _REQUIRED_TEMPLATE_KEYS if k not in definition]
    if missing_keys:
        raise InvalidTemplateError(
            f"Template '{template_id}' is missing required keys: {missing_keys}"
        )

    return definition


def _organ_matches(finding_organ: Optional[str], expected: str) -> bool:
    """
    Simple case-insensitive match between a Finding's organ and an
    expected_organs_or_regions entry. Kept deliberately simple for
    the MVP — no fuzzy matching, no synonyms beyond what's already
    explicit in the template's expected list.
    """
    if finding_organ is None:
        return False
    return finding_organ.strip().lower() == expected.strip().lower()


def build_report(
    findings: List[Finding],
    template_id: str,
    indication: str,
    technique: Optional[str] = None,
    templates_dir: Optional[str] = None,
) -> Report:
    """
    Assembles a Report from a list of Finding objects using the named
    template definition.

    - `indication` is required and always comes from the caller
      (never inferred or invented).
    - `technique` defaults to the template's `default_technique_text`
      if not provided — this is a configured default, not a guess
      about what was actually done.
    - The `impression` is built only from findings with status
      "ACTIVE" (i.e. positive findings) — NO_FINDING entries describe
      normal/evaluated regions and belong in the body of the report,
      not the impression, to avoid cluttering the summary with
      negatives.
    - Findings whose `organ` does not match any entry in the
      template's expected_organs_or_regions are still included in the
      report (never silently dropped), but are NOT used to validate
      template fit — that validation belongs to the Quality Engine.

    This function does not call recompute_status() — that is the
    Quality Engine's responsibility, run after this step.
    """
    definition = load_template(template_id, templates_dir=templates_dir)

    resolved_technique = technique or definition.get("default_technique_text", "")

    positive_findings = [f for f in findings if f.status == "ACTIVE"]
    normal_findings = [f for f in findings if f.status == "NO_FINDING"]

    if positive_findings:
        impression_lines = [
            f"- {f.description}" for f in positive_findings
        ]
        impression = "\n".join(impression_lines)
    else:
        impression = "Sin hallazgos patológicos significativos."

    report = Report(
        indication=indication,
        technique=resolved_technique,
        findings=findings,
        impression=impression,
        template_id=template_id,
    )

    return report
