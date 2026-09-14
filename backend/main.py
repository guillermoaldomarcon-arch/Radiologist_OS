"""
backend/main.py
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _subdir in ("", "models", "engines", "integrations"):
    _path = os.path.join(_REPO_ROOT, _subdir) if _subdir else _REPO_ROOT
    if _path not in sys.path:
        sys.path.insert(0, _path)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from template_engine import load_template, TemplateNotFoundError
from parser_engine import parse
from line_based_report_engine import build_line_based_report, render_report_text

import devil_advocate_engine
import differential_engine
import diagnosis_phrasing_engine
import quality_engine


app = FastAPI(title="Radiologist_OS API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_call_claude():
    from claude_client import call_claude, ClaudeClientError
    return call_claude, ClaudeClientError


class ReportRequest(BaseModel):
    template_id: str = Field(..., description="Ej: 'tc_cerebro', 'eco_abdominal'")
    dictation_text: str = Field(..., description="Dictado libre del medico")
    indication: str | None = Field(default=None, description="Motivo de estudio")


class DevilQuestionOut(BaseModel):
    finding_name: str | None
    question: str
    reason: str
    rule_type: str
    severity: str
    missing_fields: dict
    closure_candidates: dict


class DifferentialEntryOut(BaseModel):
    name: str
    likelihood: str
    rationale: str


class DifferentialStateOut(BaseModel):
    finding_name: str
    differentials: list[DifferentialEntryOut]
    next_question: str | None
    resolved: bool
    evidence_source: str
    validado_por_medico: bool


class PhrasingOptionOut(BaseModel):
    style: str
    text: str


class PhrasingResultOut(BaseModel):
    finding_name: str
    diagnosis_key: str
    options: list[PhrasingOptionOut]
    resolved_style: str | None
    evidence_source: str


class QualityIssueOut(BaseModel):
    finding_name: str | None
    reason: str
    layer: int


class ReportResponse(BaseModel):
    template_id: str
    display_name: str
    report_text: str
    unmatched_findings: list[str]
    devil_questions: list[DevilQuestionOut] = []
    differential_panel: list[DifferentialStateOut] = []
    phrasing_suggestions: list[PhrasingResultOut] = []
    quality_issues: list[QualityIssueOut] = []
    releasable: bool = True


def _devil_question_to_out(q) -> DevilQuestionOut:
    return DevilQuestionOut(
        finding_name=q.finding.name if q.finding else None,
        question=q.question, reason=q.reason, rule_type=q.rule_type,
        severity=q.severity, missing_fields=q.missing_fields,
        closure_candidates=q.closure_candidates,
    )


def _differential_state_to_out(s) -> DifferentialStateOut:
    return DifferentialStateOut(
        finding_name=s.finding_name,
        differentials=[
            DifferentialEntryOut(name=d.name, likelihood=d.likelihood, rationale=d.rationale)
            for d in s.differentials
        ],
        next_question=s.next_question, resolved=s.resolved,
        evidence_source=s.evidence_source, validado_por_medico=s.validado_por_medico,
    )


def _phrasing_result_to_out(r) -> PhrasingResultOut:
    return PhrasingResultOut(
        finding_name=r.finding_name, diagnosis_key=r.diagnosis_key,
        options=[PhrasingOptionOut(style=o.style, text=o.text) for o in r.options],
        resolved_style=r.resolved_style, evidence_source=r.evidence_source,
    )


def _quality_issue_to_out(qi) -> QualityIssueOut:
    return QualityIssueOut(
        finding_name=qi.finding.name if qi.finding else None,
        reason=qi.reason, layer=qi.layer,
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/templates")
def list_templates():
    templates_dir = os.path.join(_REPO_ROOT, "templates")
    ids = [f[:-5] for f in os.listdir(templates_dir) if f.endswith(".json")]
    result = []
    for tid in sorted(ids):
        try:
            tpl = load_template(tid)
            result.append({
                "template_id": tid,
                "display_name": tpl.get("display_name", tid),
                "modality": tpl.get("modality"),
            })
        except Exception:
            continue
    return result


@app.post("/report", response_model=ReportResponse)
def create_report(req: ReportRequest):
    try:
        template = load_template(req.template_id)
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail=f"Template '{req.template_id}' no encontrado.")

    if not req.dictation_text.strip():
        raise HTTPException(status_code=400, detail="dictation_text no puede estar vacio.")

    call_claude, ClaudeClientError = _get_call_claude()

    try:
        findings = parse(
            req.dictation_text, call_claude=call_claude,
            organ_hints=template["expected_organs_or_regions"],
        )
        report_dict = build_line_based_report(template, findings, call_claude)
    except ClaudeClientError as e:
        raise HTTPException(status_code=502, detail=f"Error llamando a Claude: {e}")

    report_text = render_report_text(template, report_dict)
    modality = template.get("modality", "")

    # Quality Engine corre DESPUES de armar el texto del informe (nunca
    # antes: build_line_based_report() solo toma findings ACTIVE, asi
    # que flaguear antes harÃ­a desaparecer el hallazgo del informe sin
    # dejar rastro). review() es puro -- no muta status todavÃ­a.
    try:
        quality_issues = quality_engine.review(
            findings, expected_organs_or_regions=template["expected_organs_or_regions"],
            original_text=req.dictation_text, call_claude=call_claude,
        )
    except Exception:
        quality_issues = []

    # devil_advocate corre con los findings TODAVIA en status=ACTIVE:
    # su Regla F necesita verlos asÃ­ para poder avisar "hay hallazgos
    # marcados, resolvelos antes de cerrar la impresiÃ³n". ReciÃ©n
    # DESPUES de esta llamada se aplican los flags reales (Layer 3).
    try:
        devil_questions_raw = devil_advocate_engine.review(findings, modality=modality, quality_issues=quality_issues)
    except Exception:
        devil_questions_raw = []

    quality_engine.apply_flags(quality_issues)
    releasable = not any(f.status == "FLAGGED" for f in findings)

    try:
        differential_raw = differential_engine.evaluate_all(findings, clinical_indication=req.indication or "")
    except Exception:
        differential_raw = []

    try:
        phrasing_raw = diagnosis_phrasing_engine.generate_phrasing_for_report(findings, modality=modality)
    except Exception:
        phrasing_raw = []

    return ReportResponse(
        template_id=req.template_id,
        display_name=template.get("display_name", req.template_id),
        report_text=report_text,
        unmatched_findings=[f.description for f in report_dict["unmatched_findings"]],
        devil_questions=[_devil_question_to_out(q) for q in devil_questions_raw],
        differential_panel=[_differential_state_to_out(s) for s in differential_raw],
        phrasing_suggestions=[_phrasing_result_to_out(r) for r in phrasing_raw],
        quality_issues=[_quality_issue_to_out(qi) for qi in quality_issues],
        releasable=releasable,
    )
