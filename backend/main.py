"""
backend/main.py

Backend FastAPI minimo para Radiologist_OS.

Expone UN endpoint generico (POST /report) que arma un informe a partir
de un dictado libre + un template_id, usando el pipeline v2 ya validado:

    parser_engine.parse()
        -> line_based_report_engine.build_line_based_report()
        -> line_based_report_engine.render_report_text()

No usa template_engine.build_report() ni quality_engine.py (este ultimo
esta roto / incompleto hoy -- ver nota en el chat). Esa es una decision
de diseno explicita, no un descuido: es el unico pipeline funcional y
ademas es el que refleja el flujo real de trabajo de Guille.

Requiere la variable de entorno ANTHROPIC_API_KEY (la usa
integrations/claude_client.py). Sin esa variable, el servidor arranca
igual pero /report devuelve 500 al primer intento de llamar a la IA.
"""

import os
import sys

# --- Resolucion de imports -------------------------------------------------
# El repo no es un paquete Python instalable: cada engine usa imports
# "planos" (from finding import Finding, from parser_engine import parse,
# etc.), asumiendo que su propia carpeta esta en sys.path. Replicamos
# exactamente el mismo setup que ya usan tests/ y run_pipeline_demo.py.

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


app = FastAPI(title="Radiologist_OS API", version="0.1.0")

# CORS abierto: uso interno de un solo medico, sin frontend publico
# todavia. Restringir origenes cuando exista un dominio fijo de frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_call_claude():
    """
    Devuelve la funcion call_claude real. Se importa recien aca (no al
    tope del modulo) para que /health y /templates funcionen incluso
    si el paquete `anthropic` no esta instalado o ANTHROPIC_API_KEY no
    esta seteada -- el error solo debe aparecer cuando /report
    realmente necesita llamar a la IA.
    """
    from claude_client import call_claude, ClaudeClientError

    return call_claude, ClaudeClientError


class ReportRequest(BaseModel):
    template_id: str = Field(..., description="Ej: 'tc_cerebro', 'eco_abdominal'")
    dictation_text: str = Field(..., description="Dictado libre del medico")
    indication: str | None = Field(
        default=None, description="Motivo de estudio / indicacion clinica"
    )


class ReportResponse(BaseModel):
    template_id: str
    display_name: str
    report_text: str
    unmatched_findings: list[str]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/templates")
def list_templates():
    """
    Lista los templates disponibles. Util para que un futuro frontend
    arme un selector sin hardcodear IDs.
    """
    templates_dir = os.path.join(_REPO_ROOT, "templates")
    ids = [
        f[:-5]
        for f in os.listdir(templates_dir)
        if f.endswith(".json")
    ]
    result = []
    for tid in sorted(ids):
        try:
            tpl = load_template(tid)
            result.append(
                {
                    "template_id": tid,
                    "display_name": tpl.get("display_name", tid),
                    "modality": tpl.get("modality"),
                }
            )
        except Exception:
            # Un template corrupto no debe tirar abajo el listado
            # completo -- se omite y listo (no se oculta el error,
            # simplemente no bloquea a los demas templates validos).
            continue
    return result


@app.post("/report", response_model=ReportResponse)
def create_report(req: ReportRequest):
    try:
        template = load_template(req.template_id)
    except TemplateNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{req.template_id}' no encontrado.",
        )

    if not req.dictation_text.strip():
        raise HTTPException(
            status_code=400, detail="dictation_text no puede estar vacio."
        )

    call_claude, ClaudeClientError = _get_call_claude()

    try:
        findings = parse(
            req.dictation_text,
            call_claude=call_claude,
            organ_hints=template["expected_organs_or_regions"],
        )
        report_dict = build_line_based_report(template, findings, call_claude)
    except ClaudeClientError as e:
        # Un fallo de la API de Claude NUNCA debe interpretarse como
        # "sin hallazgos" -- se propaga como error explicito (mismo
        # principio que ya aplican parser_engine y claude_client.py).
        raise HTTPException(status_code=502, detail=f"Error llamando a Claude: {e}")

    report_text = render_report_text(template, report_dict)

    return ReportResponse(
        template_id=req.template_id,
        display_name=template.get("display_name", req.template_id),
        report_text=report_text,
        unmatched_findings=[f.description for f in report_dict["unmatched_findings"]],
    )
