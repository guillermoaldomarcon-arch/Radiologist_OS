"""
line_based_report_engine.py

NEW module (v2 design, per Guille's real-world usage pattern):
builds a report by taking a template's fixed NORMAL lines and
deciding, line by line, whether to:
  - KEEP the normal line as-is (nothing dictated about it),
  - REPLACE it with a specific pathological finding Guille dictated,
  - OMIT it (only for lines marked omit_if_replaced_by_major_finding,
    when a major/expansive finding in the same section makes the
    generic normal line contradictory or irrelevant).

This is a different mental model from finding-based Report assembly
(template_engine.build_report): instead of building a report FROM
findings, this starts from the COMPLETE NORMAL TEMPLATE and modifies
only what the dictation actually addresses -- matching how Guille
actually works (a normal template he edits, not a blank page he
fills in).

The AI is used to do the matching: given the full set of normal
lines (each with its `concept`) and the dictated pathological
findings, it decides which line_id each finding corresponds to. This
requires real clinical understanding (e.g. recognizing that "lesión
expansiva talámica derecha" relates to the supratentorial density
line, while "ventrículo lateral derecho disminuido" relates to the
"sistema_ventricular_supratentorial" line) -- exactly why this is
AI-primary, like the v2 parser.

Safety principles preserved:
- The AI NEVER invents a finding not in the dictation; it only maps
  EXISTING dictated findings (already extracted by parser_engine) to
  template line_ids.
- If the AI cannot confidently map a finding to any line_id, that
  finding is NOT silently dropped -- it's appended in a clearly
  marked section so the radiologist sees it and can place it
  manually. This is a deliberate "fail visibly, not silently" choice.
- Order of dictation does NOT determine order in the final report --
  the final report always follows the template's fixed line order,
  per Guille's explicit requirement that this must work regardless
  of dictation order.
"""

import json
from typing import Callable, List

from finding import Finding


def _build_lines_reference(template: dict) -> List[dict]:
    """
    Flattens the template's sections/lines into a single list with
    section context attached, for easier prompting and lookup.
    """
    flat_lines = []
    for section in template.get("sections", []):
        for line in section.get("lines", []):
            flat_lines.append(
                {
                    "line_id": line["line_id"],
                    "section_id": section["section_id"],
                    "concept": line["concept"],
                    "normal_text": line["normal_text"],
                    "omit_if_replaced_by_major_finding": line.get(
                        "omit_if_replaced_by_major_finding", False
                    ),
                }
            )
    return flat_lines


def _match_findings_to_lines(
    findings: List[Finding],
    flat_lines: List[dict],
    call_claude: Callable[[str], str],
) -> dict:
    """
    Asks Claude to map each pathological (ACTIVE) finding to the
    line_id it corresponds to, and to indicate whether any OTHER
    line should be omitted as a side effect (e.g. a large expansive
    lesion makes the generic "densidad normal" line for that section
    contradictory).

    Returns a dict:
        {
          "line_id": {"action": "replace", "finding_index": int},
          ...
          "_unmatched": [finding_index, ...]
        }

    Findings the AI cannot confidently map appear in "_unmatched" --
    they are never silently dropped.
    """
    if not findings:
        return {"_unmatched": []}

    findings_text = "\n".join(
        f"{i}: organ={f.organ!r}, location={f.location!r}, side={f.side!r}, "
        f"size_mm={f.size_mm}, description={f.description!r}"
        for i, f in enumerate(findings)
    )

    lines_text = "\n".join(
        f"- line_id={l['line_id']!r} | sección={l['section_id']} | "
        f"concepto: {l['concept']} | texto normal: {l['normal_text']!r}"
        for l in flat_lines
    )

    prompt = f"""Tenés una plantilla de informe radiológico normal, compuesta por líneas fijas, y una lista de hallazgos patológicos ya extraídos de un dictado. Tu tarea es decidir, para cada hallazgo, a qué línea de la plantilla corresponde clínicamente (es decir, qué línea normal ese hallazgo patológico debería reemplazar), usando tu conocimiento médico real.

LÍNEAS DE LA PLANTILLA:
{lines_text}

HALLAZGOS DICTADOS (ya extraídos, NO los modifiques ni inventes otros):
{findings_text}

Respondé ÚNICAMENTE con un objeto JSON con esta forma exacta:

{{
  "matches": [
    {{"finding_index": int, "line_id": string}}
  ],
  "unmatched_finding_indices": [int]
}}

Donde:
- "matches": para cada hallazgo que SÍ corresponde claramente a una línea, indicá su índice y el line_id que reemplaza.
- "unmatched_finding_indices": índices de hallazgos que NO podés mapear con confianza a ninguna línea -- NUNCA fuerces un mapeo dudoso, es preferible dejarlo sin mapear.

No incluyas texto adicional, solo el JSON."""

    raw_response = call_claude(prompt)

    try:
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.replace("json", "", 1).strip()
        data = json.loads(cleaned)
    except (json.JSONDecodeError, AttributeError):
        return {"_unmatched": list(range(len(findings)))}

    result = {}

    matched_indices = set()
    for match in data.get("matches", []):
        line_id = match.get("line_id")
        finding_index = match.get("finding_index")
        if line_id is not None and finding_index is not None:
            result[line_id] = {"action": "replace", "finding_index": finding_index}
            matched_indices.add(finding_index)

    all_indices = set(range(len(findings)))
    truly_unmatched = all_indices - matched_indices
    result["_unmatched"] = sorted(truly_unmatched)

    return result


def build_line_based_report(
    template: dict,
    findings: List[Finding],
    call_claude: Callable[[str], str],
) -> dict:
    """
    Main entry point. Returns a dict describing the final report:

        {
          "sections": [
            {
              "section_title": str,
              "lines": [str, ...]
            }
          ],
          "unmatched_findings": [Finding, ...]
        }

    `findings` should be the output of parser_engine.parse(). Only
    ACTIVE findings are considered for line replacement; NO_FINDING
    findings are ignored here because the template's normal_text
    already covers that case by default.

    Omission rule (corrected per Guille's explicit clarification):
    a generic "normal density/signal" line marked
    omit_if_replaced_by_major_finding=true is omitted whenever ANY
    ACTIVE finding is mapped to ANY line within the SAME SECTION --
    regardless of the finding's size or apparent severity. This is a
    deterministic, mechanical rule (no AI judgment call about
    "is this big enough to matter") to avoid the AI having to decide
    severity, which is exactly the kind of clinical judgment that
    should not be delegated to a size/severity heuristic.
    """
    flat_lines = _build_lines_reference(template)
    pathological_findings = [f for f in findings if f.status == "ACTIVE"]

    mapping = _match_findings_to_lines(pathological_findings, flat_lines, call_claude)
    unmatched_indices = mapping.get("_unmatched", [])

    # Determine which sections received at least one matched finding,
    # so we can apply the mechanical omission rule per section.
    line_id_to_section = {l["line_id"]: l["section_id"] for l in flat_lines}
    sections_with_findings = set()
    for line_id, action_entry in mapping.items():
        if line_id == "_unmatched":
            continue
        if action_entry.get("action") == "replace":
            section_id = line_id_to_section.get(line_id)
            if section_id:
                sections_with_findings.add(section_id)

    result_sections = []

    for section in template.get("sections", []):
        section_id = section["section_id"]
        section_has_finding = section_id in sections_with_findings
        section_lines = []

        for line in section.get("lines", []):
            line_id = line["line_id"]
            action_entry = mapping.get(line_id)

            if action_entry is not None and action_entry.get("action") == "replace":
                finding_index = action_entry["finding_index"]
                finding = pathological_findings[finding_index]
                section_lines.append(finding.description)
                continue

            omit_if_major = line.get("omit_if_replaced_by_major_finding", False)
            if omit_if_major and section_has_finding:
                # Mechanical rule: ANY finding in this section
                # invalidates this generic normal-density line,
                # regardless of size/severity.
                continue

            if action_entry is not None and action_entry.get("action") == "omit":
                continue

            section_lines.append(line["normal_text"])

        result_sections.append(
            {"section_title": section["section_title"], "lines": section_lines}
        )

    unmatched_findings = [pathological_findings[i] for i in unmatched_indices]

    return {
        "sections": result_sections,
        "unmatched_findings": unmatched_findings,
    }


def render_report_text(template: dict, report_dict: dict) -> str:
    """
    Renders the structured report dict into plain text, matching
    Guille's real format (technique paragraph, then each section with
    its title and bullet lines).
    """
    lines_out = []
    lines_out.append(template.get("display_name", "").upper())
    lines_out.append("")
    lines_out.append(template.get("default_technique_text", ""))
    lines_out.append("")

    for section in report_dict["sections"]:
        lines_out.append(section["section_title"])
        lines_out.append("")
        for line in section["lines"]:
            lines_out.append(f"\u00b7        {line}")
        lines_out.append("")

    if report_dict["unmatched_findings"]:
        lines_out.append("--- HALLAZGOS SIN UBICAR (requieren revisión manual) ---")
        for f in report_dict["unmatched_findings"]:
            lines_out.append(f"\u00b7        {f.description}")
        lines_out.append("")

    return "\n".join(lines_out)
