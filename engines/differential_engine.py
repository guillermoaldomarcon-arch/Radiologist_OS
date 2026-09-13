"""
differential_engine.py

Progressive differential-diagnosis copilot. Runs alongside the
report, outside of it -- it never touches Finding.description or any
report text. Given ONE Finding (already extracted, organ-scoped, and
verified by Parser/Quality Engines), narrows a differential as more
descriptors become available, and states what's still missing to
narrow it further.

Design principle (per project philosophy):
Same as every other engine here -- never invents a descriptor that
wasn't dictated. `resolved=True` means the decision tree reached a
terminal branch given the data available, NOT "diagnosis confirmed."

Why this replaced an earlier text-scoping prototype:
An earlier version worked directly on raw report text and needed
manual "which organ does this sentence belong to" logic (excluding
"higado"/"tiroide"/etc. keywords when scoping to a lung finding, and
a separate cut-point heuristic to stop an organ-level normal phrase
like "hígado ... densidad homogénea" from being misread as describing
an adjacent focal finding). None of that is needed anymore: Parser
Engine (v2) already produced one Finding per distinct finding, with
its own `organ` and `description` -- this module just has to pick the
right Finding by `organ` and read its own fields.

The one piece of that old scoping logic kept here (see
_lesion_specific_text) is a defensive cut at phrases like
"destacándose" within a single Finding's own description -- not
because Parser is expected to need it, but because the AI-driven
extraction hasn't been checked against enough real cases yet to be
sure it never includes organ-level preamble inside one finding's
description. Cheap to keep, does nothing if the description is
already clean.

Clinical trees implemented so far (each validated against real cases
from Guille's practice, with corrections he made explicitly -- see
project history for what changed and why):
  - Solid pulmonary nodule
  - Hepatic lesion (incidental, non-dedicated-protocol scenario)
Both PENDING `validado_por_medico = True` sign-off is tracked
per-tree at the module level below -- flip explicitly once confirmed,
never assume.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional

from finding import Finding


_ACCENT_MAP = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")


def _strip_accents(text: str) -> str:
    """Same utility parser_engine.py already uses. Reused here instead
    of re-inventing accent handling per keyword, which is exactly how
    the 'hepat' vs 'hepático' bug happened in the first place."""
    return text.translate(_ACCENT_MAP)


@dataclass
class DifferentialEntry:
    name: str
    likelihood: str
    rationale: str


@dataclass
class DifferentialState:
    finding_name: str                        # Finding.name this state is about
    differentials: list[DifferentialEntry]
    next_question: Optional[str]
    resolved: bool                            # terminal branch reached -- NOT "confirmed"
    evidence_source: str
    validado_por_medico: bool = False


# Per-tree validation status. Flip explicitly once Guille confirms --
# never assume validation from a clean test run alone.
TREE_VALIDATION_STATUS = {
    "nodulo_pulmonar_solido": True,   # confirmado: orden por frecuencia + tamaño corregido
    "lesion_hepatica": False,          # umbral HU y patrones de realce sin caso real que los confirme
}


def _lesion_specific_text(text: str) -> str:
    """Defensive cut at the point a focal finding starts within a
    single Finding's own description (see module docstring)."""
    markers = ["destacandose", "destacándose", "con imagen", "que muestra",
               "se observa", "se visualiza"]
    t_low = text.lower()
    best_idx = None
    for m in markers:
        idx = t_low.find(m)
        if idx != -1 and (best_idx is None or idx < best_idx):
            best_idx = idx
    return text[best_idx:] if best_idx is not None else text


# ═══════════════════════════════════════════════════════════════════
# ÁRBOL 1: NÓDULO PULMONAR SÓLIDO
# Fuente: Radiology Assistant, RadioGraphics/RSNA, Applied Radiology.
# Orden base y peso del tamaño CORREGIDOS por el médico -- ver
# project history: granuloma/hamartoma preceden a neoplasia por
# frecuencia real, y el tamaño (<5mm -> <1% malignidad, AAFP) es más
# determinante que márgenes/calcificación en nódulos pequeños.
# ═══════════════════════════════════════════════════════════════════

_EVIDENCE_SPN = (
    "Radiology Assistant, RadioGraphics/RSNA, Applied Radiology -- "
    "patrones de calcificación de nódulo pulmonar solitario. Orden "
    "base y peso del tamaño corregidos por el médico con cita AAFP."
)

_BENIGN_CALC_PATTERNS = {"central", "laminada", "difusa", "concentrica"}
_INDETERMINATE_CALC_PATTERNS = {"excentrica", "punteada", "amorfa"}


def evaluate_solid_pulmonary_nodule(descriptors: dict) -> DifferentialState:
    calc = descriptors.get("calcificacion")
    margenes = descriptors.get("margenes")
    tam = descriptors.get("tamaño_mm")
    antec_onc = descriptors.get("antecedente_oncologico")

    if calc == "palomita_de_maiz":
        return DifferentialState(
            finding_name="nodulo_pulmonar_solido",
            differentials=[DifferentialEntry(
                "Hamartoma", "muy probable",
                "Calcificación en palomita de maíz es diagnóstica de hamartoma.")],
            next_question=None, resolved=True, evidence_source=_EVIDENCE_SPN,
        )

    if calc in _BENIGN_CALC_PATTERNS:
        return DifferentialState(
            finding_name="nodulo_pulmonar_solido",
            differentials=[DifferentialEntry(
                "Granuloma", "muy probable",
                f"Calcificación de patrón {calc.replace('_', ' ')} es característica "
                f"de granuloma (patrón benigno: central/laminada/difusa/concéntrica).")],
            next_question=None, resolved=True, evidence_source=_EVIDENCE_SPN,
        )

    if calc == "patron_no_especificado":
        return DifferentialState(
            finding_name="nodulo_pulmonar_solido",
            differentials=[
                DifferentialEntry("Granuloma", "probable",
                    "Hay calcificación confirmada, pero el patrón exacto (no solo "
                    "'está calcificado') determina benigno vs. indeterminado."),
                DifferentialEntry("Neoplasia primaria", "posible",
                    "No descartable hasta conocer el patrón exacto."),
            ],
            next_question="Confirmaste calcificación -- ¿de qué patrón específico? "
                           "(central / laminada / difusa / concéntrica / palomita "
                           "de maíz / excéntrica / punteada / amorfa)",
            resolved=False, evidence_source=_EVIDENCE_SPN,
        )

    if calc is None:
        size_note, neoplasia_likelihood = "", "posible"
        if tam is not None:
            if tam < 5:
                size_note = f" Tamaño de {tam:.0f}mm -- <5mm: <1% malignidad (AAFP)."
                neoplasia_likelihood = "poco probable"
            elif tam < 10:
                size_note = f" Tamaño de {tam:.0f}mm -- 5-10mm: 6-28% malignidad."
            elif tam >= 20:
                size_note = f" Tamaño de {tam:.0f}mm (≥2cm) -- 64-82% malignidad."
                neoplasia_likelihood = "probable"
        margin_note = (" Márgenes espiculados ya descriptos -- factor de riesgo "
                        "independiente, a ponderar junto con el tamaño."
                        if margenes == "espiculados" else "")
        diffs = [
            DifferentialEntry("Granuloma (infeccioso)", "probable",
                "Causa más frecuente de nódulo pulmonar benigno -- sensible a "
                "prevalencia regional de enfermedad granulomatosa."),
            DifferentialEntry("Hamartoma", "probable",
                "Tumor benigno pulmonar más frecuente (~55% de los tumores "
                "benignos de pulmón)."),
            DifferentialEntry("Neoplasia primaria", neoplasia_likelihood,
                "No descartable ni confirmable sin calcificación." + size_note + margin_note),
        ]
        if antec_onc:
            diffs.append(DifferentialEntry("Metástasis", "posible",
                "Antecedente oncológico dictado -- considerar en el diferencial."))
        return DifferentialState(
            finding_name="nodulo_pulmonar_solido", differentials=diffs,
            next_question="¿Tiene calcificación? Si la tiene, ¿de qué patrón?",
            resolved=False, evidence_source=_EVIDENCE_SPN,
        )

    calc_note = (
        "Patrón de calcificación indeterminado -- NO excluye malignidad "
        "(hasta 10% de carcinomas broncogénicos calcifican)." if calc in _INDETERMINATE_CALC_PATTERNS
        else "Sin calcificación visible -- no confirma ni descarta malignidad por sí sola."
    )

    if margenes is None:
        return DifferentialState(
            finding_name="nodulo_pulmonar_solido",
            differentials=[
                DifferentialEntry("Granuloma", "probable", calc_note),
                DifferentialEntry("Hamartoma", "probable", calc_note),
                DifferentialEntry("Neoplasia primaria", "posible", calc_note),
            ],
            next_question="¿Los márgenes son lisos, espiculados o lobulados?",
            resolved=False, evidence_source=_EVIDENCE_SPN,
        )

    if margenes == "espiculados":
        if tam is not None and tam < 5:
            diffs = [
                DifferentialEntry("Granuloma", "probable",
                    f"{calc_note} A pesar de márgenes espiculados: <5mm "
                    f"({tam:.0f}mm) tiene <1% malignidad publicada, y a este "
                    f"tamaño la evaluación de espiculación es menos confiable "
                    f"(efecto de volumen parcial)."),
                DifferentialEntry("Hamartoma", "posible", calc_note),
                DifferentialEntry("Neoplasia primaria", "posible",
                    "No excluida, pero el tamaño reduce la probabilidad pretest."),
            ]
            next_q = "¿Hay estudio previo para evaluar estabilidad/crecimiento?"
        else:
            diffs = [DifferentialEntry(
                "Neoplasia primaria", "probable",
                f"{calc_note} Márgenes espiculados sin calcificación benigna, en "
                f"nódulo {'≥5mm' if tam else 'de tamaño no confirmado'} -- "
                f"combinación asociada a malignidad.")]
            if antec_onc:
                diffs.append(DifferentialEntry("Metástasis", "posible",
                    "Antecedente oncológico dictado."))
            diffs.append(DifferentialEntry("Proceso inflamatorio/infeccioso organizado",
                "posible", "Menos frecuente con este patrón, no excluido."))
            next_q = None if tam is not None else "¿Tamaño exacto y estudio previo?"
        return DifferentialState(
            finding_name="nodulo_pulmonar_solido", differentials=diffs,
            next_question=next_q, resolved=(next_q is None), evidence_source=_EVIDENCE_SPN,
        )

    return DifferentialState(
        finding_name="nodulo_pulmonar_solido",
        differentials=[
            DifferentialEntry("Granuloma", "probable", calc_note + " Márgenes no espiculados."),
            DifferentialEntry("Hamartoma", "probable", calc_note + " Márgenes no espiculados."),
            DifferentialEntry("Neoplasia primaria", "poco probable",
                "Menos probable con márgenes lisos/lobulados, no excluida."),
        ],
        next_question="¿Tamaño y crecimiento respecto a estudio previo, si existe?",
        resolved=False, evidence_source=_EVIDENCE_SPN,
    )


def extract_calcification(text: str) -> Optional[str]:
    t = text.lower()
    if "sin calcificacion" in t or "sin calcificación" in t or "sin calcio" in t:
        return "ausente"
    if "palomita de maiz" in t or "palomita de maíz" in t or "popcorn" in t:
        return "palomita_de_maiz"
    if "laminad" in t:
        return "laminada"
    if "concentrica" in t or "concéntrica" in t:
        return "concentrica"
    if "excentrica" in t or "excéntrica" in t:
        return "excentrica"
    if "punteada" in t or "puntiforme" in t:
        return "punteada"
    if "amorfa" in t:
        return "amorfa"
    if "central" in t and "calcifica" in t:
        return "central"
    if "difusa" in t and "calcifica" in t:
        return "difusa"
    if "calcificacion" in t or "calcificado" in t or "calcio" in t:
        return "patron_no_especificado"
    return None


def extract_pulmonary_margins(text: str) -> Optional[str]:
    t = text.lower()
    if "espiculad" in t:
        return "espiculados"
    if "lobulad" in t:
        return "lobulados"
    if "liso" in t or "bien definido" in t or "circunscript" in t:
        return "lisos"
    return None


def extract_oncologic_history(text: str) -> Optional[bool]:
    t = text.lower()
    if "sin antecedente" in t and ("oncologic" in t or "cancer" in t):
        return False
    if "antecedente" in t and any(
        k in t for k in ["oncologic", "cancer", "cáncer", "carcinoma", "neoplasia", "tumor"]
    ):
        return True
    return None


def evaluate_pulmonary_nodule_finding(
    finding: Finding, clinical_indication: str = ""
) -> Optional[DifferentialState]:
    """Entry point: takes ONE Finding, returns its differential state,
    or None if this Finding isn't a pulmonary nodule."""
    if not any(k in _strip_accents((finding.organ or "").lower()) for k in ("pulmon", "pulmonar")):
        return None
    desc = _lesion_specific_text(finding.description or "")
    descriptors = {
        "calcificacion": extract_calcification(desc),
        "margenes": extract_pulmonary_margins(desc),
        "tamaño_mm": finding.size_mm,
        "antecedente_oncologico": extract_oncologic_history(clinical_indication + " " + desc),
    }
    state = evaluate_solid_pulmonary_nodule(descriptors)
    state.finding_name = finding.name
    state.validado_por_medico = TREE_VALIDATION_STATUS["nodulo_pulmonar_solido"]
    return state


# ═══════════════════════════════════════════════════════════════════
# ÁRBOL 2: LESIÓN HEPÁTICA INCIDENTAL
# ═══════════════════════════════════════════════════════════════════

_EVIDENCE_HEPATIC = (
    "ACR Incidental Findings Committee White Paper (JACR 2017). "
    "Discriminación morfológica y gate de metástasis explícita "
    "agregados por corrección del médico."
)

_EXPLICIT_HEPATIC_DIAGNOSIS_RE = re.compile(r"metastasi\w*|metástasi\w*", re.IGNORECASE)


def evaluate_hepatic_lesion(descriptors: dict) -> DifferentialState:
    tam = descriptors.get("tamaño_mm")
    hu = descriptors.get("densidad_hu")
    homogeneidad = descriptors.get("homogeneidad")
    margenes = descriptors.get("margenes")
    realce = descriptors.get("patron_realce")
    riesgo = descriptors.get("riesgo_paciente")

    if realce == "nodular_periferico_progresivo":
        return DifferentialState(
            finding_name="lesion_hepatica",
            differentials=[DifferentialEntry(
                "Hemangioma", "muy probable",
                "Realce nodular periférico con relleno progresivo centrípeto es "
                "el patrón característico de hemangioma.")],
            next_question=None, resolved=True, evidence_source=_EVIDENCE_HEPATIC,
        )

    if realce == "arterial_homogeneo_cicatriz_central":
        return DifferentialState(
            finding_name="lesion_hepatica",
            differentials=[DifferentialEntry(
                "Hiperplasia nodular focal (FNH)", "probable",
                "Realce arterial homogéneo con cicatriz central es característico "
                "de FNH. Confirmación adicional: fase hepatobiliar con gadoxetato.")],
            next_question=None, resolved=True, evidence_source=_EVIDENCE_HEPATIC,
        )

    if realce is None:
        if hu is not None and hu <= 20 and (margenes is None or margenes == "redondeados_nitidos"):
            return DifferentialState(
                finding_name="lesion_hepatica",
                differentials=[DifferentialEntry(
                    "Quiste hepático simple", "muy probable",
                    f"Densidad de {hu:.0f} HU (≤20) compatible con líquido -- "
                    f"criterio ACR para quiste simple.")],
                next_question=None, resolved=True, evidence_source=_EVIDENCE_HEPATIC,
            )
        if homogeneidad == "homogenea" and margenes == "redondeados_nitidos":
            return DifferentialState(
                finding_name="lesion_hepatica",
                differentials=[DifferentialEntry(
                    "Quiste hepático simple", "probable",
                    "Densidad homogénea con márgenes redondeados/nítidos, pared "
                    "fina -- patrón típico de quiste, aún sin HU ni contraste.")],
                next_question=None, resolved=True, evidence_source=_EVIDENCE_HEPATIC,
            )
        if homogeneidad == "no_homogenea" or margenes == "mal_definidos":
            return DifferentialState(
                finding_name="lesion_hepatica",
                differentials=[
                    DifferentialEntry("Hemangioma", "probable",
                        "Densidad no homogénea y/o márgenes menos definidos/"
                        "redondeados que un quiste -- más compatible con "
                        "hemangioma, sin patrón de realce confirmatorio."),
                    DifferentialEntry("Indeterminado", "posible",
                        "Morfología no típica de quiste; sin fase de contraste "
                        "no se confirma hemangioma con certeza." + (
                            " Riesgo del paciente elevado." if riesgo == "alto" else "")),
                ],
                next_question="¿Se realizó fase arterial con contraste?",
                resolved=False, evidence_source=_EVIDENCE_HEPATIC,
            )
        size_note = (f" A {tam:.0f}mm (<1cm), la medición de densidad suele no "
                     f"ser confiable (criterio ACR)." if tam is not None and tam < 10 else "")
        diffs = [
            DifferentialEntry("Quiste hepático simple", "probable",
                "Causa más frecuente de lesión hepática hipodensa incidental." + size_note),
            DifferentialEntry("Hemangioma", "probable",
                "Lesión sólida benigna hepática más frecuente."),
            DifferentialEntry("Indeterminado", "posible",
                "Sin HU, homogeneidad, márgenes ni realce -- sin criterio "
                "discriminante disponible." + (
                    " Riesgo del paciente elevado." if riesgo == "alto" else "")),
        ]
        return DifferentialState(
            finding_name="lesion_hepatica", differentials=diffs,
            next_question="¿Densidad homogénea o no? ¿Márgenes redondeados/nítidos "
                           "o mal definidos? ¿HU o fase arterial? ¿Antecedente "
                           "oncológico o hepatopatía?",
            resolved=False, evidence_source=_EVIDENCE_HEPATIC,
        )

    diffs = [DifferentialEntry(
        "Indeterminado -- características sospechosas", "posible",
        "Márgenes mal definidos, densidad heterogénea o >20 HU en fase "
        "portal son criterios ACR de sospecha, requieren caracterización adicional.")]
    if riesgo == "alto":
        diffs.insert(0, DifferentialEntry(
            "Metástasis / hepatocarcinoma (según contexto)", "posible",
            "Paciente de riesgo alto -- el mismo hallazgo pesa más hacia malignidad."))
    return DifferentialState(
        finding_name="lesion_hepatica", differentials=diffs,
        next_question=None, resolved=True, evidence_source=_EVIDENCE_HEPATIC,
    )


_HU_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:hu\b|unidades?\s+hounsfield)", re.IGNORECASE)


def extract_hu(text: str) -> Optional[float]:
    m = _HU_RE.search(text)
    return float(m.group(1).replace(",", ".")) if m else None


def extract_hepatic_margins(text: str) -> Optional[str]:
    t = _lesion_specific_text(text).lower()
    if "mal definid" in t or "irregular" in t or "indistint" in t:
        return "mal_definidos"
    if "redondead" in t or "nitido" in t or "nítido" in t or "bien definid" in t or "pared fina" in t:
        return "redondeados_nitidos"
    return None


def extract_homogeneity(text: str) -> Optional[str]:
    t = _lesion_specific_text(text).lower()
    if "no homogene" in t or "heterogene" in t:
        return "no_homogenea"
    if "homogene" in t:
        return "homogenea"
    return None


def extract_enhancement_pattern(text: str) -> Optional[str]:
    t = text.lower()
    if ("relleno progresivo" in t or "realce nodular periferico" in t
            or "centripeto" in t or "centrípeto" in t):
        return "nodular_periferico_progresivo"
    if "cicatriz central" in t and ("realce" in t or "arterial" in t):
        return "arterial_homogeneo_cicatriz_central"
    if "heterogene" in t and ("realce" in t or "contraste" in t):
        return "heterogeneo"
    if "sin realce" in t or "no capta contraste" in t:
        return "sin_realce"
    return None


def extract_hepatic_risk(text: str) -> Optional[str]:
    t = text.lower()
    if any(k in t for k in ["cirrosis", "hepatopatia cronica", "hepatopatía crónica"]):
        return "alto"
    onc = extract_oncologic_history(text)
    if onc is True:
        return "alto"
    if onc is False:
        return "bajo"
    return None


def evaluate_hepatic_lesion_finding(
    finding: Finding, clinical_indication: str = ""
) -> Optional[DifferentialState]:
    if not any(k in _strip_accents((finding.organ or "").lower()) for k in ("higado", "hepat")):
        return None
    desc = finding.description or ""

    if _EXPLICIT_HEPATIC_DIAGNOSIS_RE.search(desc) or _EXPLICIT_HEPATIC_DIAGNOSIS_RE.search(finding.name or ""):
        state = DifferentialState(
            finding_name=finding.name,
            differentials=[DifferentialEntry(
                "Metástasis hepática -- dictado explícitamente por el médico",
                "confirmado por el médico",
                "El médico ya dictó este diagnóstico directamente. El árbol no "
                "se activa sobre un hallazgo ya resuelto por criterio clínico.")],
            next_question=None, resolved=True,
            evidence_source="Dictado directo del médico -- sin inferencia del sistema.",
        )
        state.validado_por_medico = True
        return state

    scoped = _lesion_specific_text(desc)
    descriptors = {
        "tamaño_mm": finding.size_mm,
        "densidad_hu": extract_hu(scoped),
        "margenes": extract_hepatic_margins(desc),
        "homogeneidad": extract_homogeneity(desc),
        "patron_realce": extract_enhancement_pattern(desc),
        "riesgo_paciente": extract_hepatic_risk(clinical_indication + " " + desc),
    }
    state = evaluate_hepatic_lesion(descriptors)
    state.finding_name = finding.name
    state.validado_por_medico = TREE_VALIDATION_STATUS["lesion_hepatica"]
    return state


# ---------------------------------------------------------------------------
# Entry point over a full finding list
# ---------------------------------------------------------------------------

FINDING_EVALUATORS = [
    evaluate_pulmonary_nodule_finding,
    evaluate_hepatic_lesion_finding,
]


def evaluate_all(
    findings: list, clinical_indication: str = ""
) -> list:
    """Runs every registered tree against every ACTIVE finding, returns
    only the states that actually matched (organ recognized by some tree)."""
    results = []
    for f in findings:
        if f.status != "ACTIVE":
            continue
        for evaluator in FINDING_EVALUATORS:
            state = evaluator(f, clinical_indication)
            if state is not None:
                results.append(state)
    return results
