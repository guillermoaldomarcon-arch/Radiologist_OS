"""
diagnosis_phrasing_engine.py

Diagnosis dictated directly -> descriptive report text, in two
registers (descriptivo/conciso), with per-diagnosis style learning.

Reverse direction from differential_engine.py: there, the radiologist
dictates findings and the system suggests diagnoses. Here the
radiologist dictates the DIAGNOSIS itself (e.g. "hígado con esteatosis
grado II") and this module proposes the report text.

Design principle, confirmed by Guille explicitly:
Two content sources, in this precedence order:
  1. Explicit correction by the radiologist (always wins, once
     recorded -- see StylePreferenceStore).
  2. Verified external literature (this module's default source --
     preferred over the radiologist's own past reports, because past
     reports can carry errors that good literature doesn't).
  3. Extraction from the radiologist's own past reports (dictionary
     engine -- lowest precedence; NOT found in this repo as of this
     port, may not exist yet).

Fidelity distinction (also confirmed explicitly):
  - Fixed methodological boilerplate for a diagnosis category (e.g.
    "comparación de densidad hepatoesplénica" for steatosis, or the
    grade-specific vessel/diaphragm-visibility criteria for
    ultrasound steatosis grading) is safe to auto-complete -- it's
    not a patient-specific claim, it's how that entity is described
    in any case.
  - Patient-specific morphological detail (e.g. "contornos
    regulares" for an FNH) is NEVER invented -- only included if the
    radiologist actually dictated it. If not dictated, that clause is
    omitted, not filled with a typical/default value.

Why this replaced a raw-text-scoping prototype:
Diagnosis detection and slot extraction now run against a single
Finding's own `description`/`name`, not the whole report text with an
ad-hoc sentence-splitting scan. Location and size no longer need
re-extraction from text at all: Finding.location/side/size_mm already
carry that (verified) data from Parser Engine.
"""

from __future__ import annotations
import re
from collections import Counter
from typing import Optional

from finding import Finding


class PhrasingOption:
    def __init__(self, style: str, text: str):
        self.style = style
        self.text = text

    def __repr__(self) -> str:
        return f"PhrasingOption(style={self.style!r})"


class PhrasingResult:
    def __init__(
        self, finding_name: str, diagnosis_key: str, options: list,
        resolved_style: Optional[str], evidence_source: str,
    ):
        self.finding_name = finding_name
        self.diagnosis_key = diagnosis_key
        self.options = options
        self.resolved_style = resolved_style
        self.evidence_source = evidence_source

    def __repr__(self) -> str:
        return (f"PhrasingResult(finding={self.finding_name!r}, "
                f"diagnosis={self.diagnosis_key!r}, resolved={self.resolved_style!r})")


def _format_size(mm: Optional[float]) -> Optional[str]:
    if mm is None:
        return None
    if mm >= 10:
        cm = mm / 10
        return f"{cm:.1f} cm".replace(".0 cm", " cm")
    return f"{mm:.0f} mm"


def _build_location_phrase(finding: Finding) -> Optional[str]:
    if finding.location:
        return finding.location
    if finding.side and finding.organ:
        return f"{finding.organ} {finding.side}"
    return None


def extract_contornos(text: str) -> Optional[str]:
    t = (text or "").lower()
    if "contornos regulares" in t or "bien definid" in t:
        return "regulares"
    if "contornos irregulares" in t or "mal definid" in t:
        return "irregulares"
    if "contornos lobulados" in t:
        return "lobulados"
    return None


def extract_grado(text: str) -> Optional[str]:
    m = re.search(r"grado\s+(i{1,3}|1|2|3)\b", (text or ""), re.IGNORECASE)
    if not m:
        return None
    val = m.group(1).upper()
    return {"1": "I", "2": "II", "3": "III"}.get(val, val)


def extract_phrasing_slots(finding: Finding) -> dict:
    return {
        "tamaño": _format_size(finding.size_mm),
        "ubicacion": _build_location_phrase(finding),
        "contornos": extract_contornos(finding.description or ""),
        "grado": extract_grado(finding.description or ""),
    }


_ESTEATOSIS_ECO_POR_GRADO = {
    "I": {
        "descriptivo": (
            "Hígado con leve aumento difuso de la ecogenicidad, con buena "
            "definición de las paredes de los vasos intrahepáticos y del "
            "diafragma, compatible con esteatosis hepática difusa grado I (leve)."
        ),
        "conciso": "Signos ecográficos de esteatosis hepática difusa grado I (leve).",
    },
    "II": {
        "descriptivo": (
            "Hígado con aumento moderado y difuso de la ecogenicidad, con "
            "pérdida parcial de la definición de las paredes de los vasos "
            "intrahepáticos y del diafragma, compatible con esteatosis "
            "hepática difusa grado II (moderada)."
        ),
        "conciso": "Signos ecográficos de esteatosis hepática difusa grado II (moderada).",
    },
    "III": {
        "descriptivo": (
            "Hígado con marcado aumento difuso de la ecogenicidad y "
            "atenuación posterior del haz de ultrasonido, con pobre o nula "
            "visualización del diafragma y de los vasos intrahepáticos, "
            "compatible con esteatosis hepática difusa grado III (severa)."
        ),
        "conciso": "Signos ecográficos de esteatosis hepática difusa grado III (severa).",
    },
}


def _esteatosis_eco_descriptivo(slots: dict) -> str:
    grado = slots.get("grado")
    if grado in _ESTEATOSIS_ECO_POR_GRADO:
        return _ESTEATOSIS_ECO_POR_GRADO[grado]["descriptivo"]
    return ("Hígado disminuido de ecogenicidad por infiltración grasa, "
            "compatible con esteatosis hepática difusa.")


def _esteatosis_eco_conciso(slots: dict) -> str:
    grado = slots.get("grado")
    if grado in _ESTEATOSIS_ECO_POR_GRADO:
        return _ESTEATOSIS_ECO_POR_GRADO[grado]["conciso"]
    return "Signos ecográficos de esteatosis hepática difusa."


def _grado_suffix(slots: dict) -> str:
    return f" grado {slots['grado']}" if slots.get("grado") else ""


def _fnh_descriptivo(slots: dict) -> str:
    tam = slots.get("tamaño") or "(tamaño no dictado)"
    ubic = slots.get("ubicacion") or "(ubicación no dictada)"
    base = f"Destacándose imagen nodular sólida de {tam} de diámetro en el {ubic}"
    if slots.get("contornos"):
        base += f", de contornos {slots['contornos']}"
    return base + ", sugestiva de hiperplasia nodular focal."


def _fnh_conciso(slots: dict) -> str:
    tam = slots.get("tamaño") or "(tamaño no dictado)"
    ubic = slots.get("ubicacion") or "(ubicación no dictada)"
    return f"Visualizándose imagen nodular de {tam} en el {ubic} sugestiva de hiperplasia nodular focal."


DIAGNOSIS_PHRASING_BANK = {
    "esteatosis_hepatica_difusa": {
        "trigger": re.compile(r"esteatosis", re.IGNORECASE),
        "organ": "higado",
        "TC": {
            "descriptivo": lambda slots: (
                f"Disminución difusa de la densidad hepática en comparación con "
                f"el bazo, sugestivo de esteatosis hepática difusa{_grado_suffix(slots)}."
            ),
            "conciso": lambda slots: f"Signos a favor de esteatosis hepática difusa{_grado_suffix(slots)}.",
        },
        "ECO": {
            "descriptivo": _esteatosis_eco_descriptivo,
            "conciso": _esteatosis_eco_conciso,
        },
        "evidence_source": "TC: estructura provista por el médico, grado como "
                            "sufijo (sin validar graduación por densidad TC "
                            "todavía). ECO: criterio por grado verificado "
                            "(PMC11423484, AJUM 2024, PMC7652655).",
    },
    "hiperplasia_nodular_focal": {
        "trigger": re.compile(r"hiperplasia nodular focal|\bfnh\b", re.IGNORECASE),
        "organ": "higado",
        "TC": {
            "descriptivo": _fnh_descriptivo,
            "conciso": _fnh_conciso,
        },
        "evidence_source": "Estructura provista por el médico, solo validada "
                            "para TC. 'Contornos' es opcional -- solo se incluye "
                            "si fue dictado explícitamente.",
    },
}


class StylePreferenceStore:
    """In-memory STUB. Real persistence (per-radiologist, across
    sessions) belongs in the backend's database, outside this module."""

    def __init__(self):
        self._choices: dict = {}

    def record_choice(self, diagnosis_key: str, style: str) -> None:
        self._choices.setdefault(diagnosis_key, []).append(style)

    def preferred_style(
        self, diagnosis_key: str, min_samples: int = 3, threshold: float = 0.8
    ) -> Optional[str]:
        history = self._choices.get(diagnosis_key, [])
        if len(history) < min_samples:
            return None
        style, count = Counter(history).most_common(1)[0]
        return style if (count / len(history)) >= threshold else None


def generate_phrasing_for_finding(
    finding: Finding, modality: str, preference_store: Optional[StylePreferenceStore] = None
) -> Optional[PhrasingResult]:
    text = f"{finding.name or ''} {finding.description or ''}"
    for diag_key, entry in DIAGNOSIS_PHRASING_BANK.items():
        if not entry["trigger"].search(text):
            continue
        modality_bank = entry.get(modality.upper())
        if not modality_bank:
            return None

        slots = extract_phrasing_slots(finding)
        options = [
            PhrasingOption("descriptivo", modality_bank["descriptivo"](slots)),
            PhrasingOption("conciso", modality_bank["conciso"](slots)),
        ]

        resolved = None
        if preference_store:
            resolved = preference_store.preferred_style(diag_key)
            if resolved:
                options = [o for o in options if o.style == resolved]

        return PhrasingResult(
            finding_name=finding.name, diagnosis_key=diag_key, options=options,
            resolved_style=resolved, evidence_source=entry["evidence_source"],
        )
    return None


def generate_phrasing_for_report(
    findings: list, modality: str, preference_store: Optional[StylePreferenceStore] = None
) -> list:
    results = []
    for f in findings:
        result = generate_phrasing_for_finding(f, modality, preference_store)
        if result:
            results.append(result)
    return results
