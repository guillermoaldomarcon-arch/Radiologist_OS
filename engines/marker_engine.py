"""
marker_engine.py

Aplica por CÓDIGO las instrucciones explícitas del médico que viajan dentro del
dictado, para que no dependan de que la IA las interprete bien:

  - "Hallazgo adicional: ..." / [UBICACION_CONFIRMADA: ... = otros_hallazgos]
        -> el hallazgo va a la sección OTROS HALLAZGOS.
  - [LATERALIDAD_CONFIRMADA: <descripción> = derecho|izquierdo|bilateral]
        -> completa el lado del hallazgo.
  - [DESCRIPTOR_CONFIRMADO: <descripción> = márgenes irregulares]
        -> agrega el descriptor a la descripción ("con márgenes irregulares").

Regla de oro: un hallazgo dictado NUNCA desaparece en silencio. Si la IA no lo
devolvió, se lo recrea con el texto literal del dictado; si el extractor no
devuelve nada pese a haber medidas, se reintenta y, si sigue igual, se falla
con un error visible en vez de entregar un informe vacío "Listo".
"""

import re
from typing import Callable, List, Optional

from finding import Finding

EXTRA_ID = "otros_hallazgos"

_MEASUREMENT_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(mm|cm)\b", re.IGNORECASE)

_EXTRA_MARKER_RE = re.compile(
    r"\[UBICACION_CONFIRMADA:\s*(.+?)\s*=\s*otros_hallazgos\s*\]", re.IGNORECASE | re.DOTALL
)
_EXTRA_KEYWORD_RE = re.compile(
    r"(?:hallazgo adicional|otro hallazgo)\s*[:\-–,]?\s*((?:[^.\n\[]|\.\d)+)", re.IGNORECASE
)
_EXTRA_PREFIX_RE = re.compile(
    r"^\s*(?:hallazgo adicional|otro hallazgo)\s*[:\-–,]?\s*", re.IGNORECASE
)
_SIDE_MARKER_RE = re.compile(
    r"\[LATERALIDAD_CONFIRMADA:\s*(.+?)\s*=\s*(derech[oa]|izquierd[oa]|bilateral)\s*\]",
    re.IGNORECASE | re.DOTALL,
)
_DESCRIPTOR_MARKER_RE = re.compile(
    r"\[DESCRIPTOR_CONFIRMADO:\s*(.+?)\s*=\s*(.+?)\s*\]", re.IGNORECASE | re.DOTALL
)

_ACCENTS = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")


def _norm(text: Optional[str]) -> str:
    return " ".join(re.findall(r"[a-zñ0-9]+", (text or "").translate(_ACCENTS).lower()))


def _word_set(text: Optional[str]) -> set:
    return {w for w in _norm(text).split() if len(w) > 2 or w.isdigit()}


def _score(a: Optional[str], b: Optional[str]) -> float:
    wa, wb = _word_set(a), _word_set(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def _best_match(findings: List[Finding], text: str, minimum: float = 0.6) -> Optional[Finding]:
    best, best_score = None, minimum
    for f in findings:
        score = _score(f.description or f.name, text)
        if score >= best_score and (best is None or score > best_score):
            best, best_score = f, score
    return best


def _size_from_text(text: str) -> Optional[float]:
    match = _MEASUREMENT_PATTERN.search(text)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    return value * 10.0 if match.group(2).lower() == "cm" else value


def _new_finding(findings: List[Finding], text: str) -> Finding:
    """Recrea un hallazgo que el extractor no devolvió, con el texto literal."""
    finding = Finding(
        name=text, organ=None, description=text, size_mm=_size_from_text(text),
        certainty="MODERATE", status="ACTIVE",
    )
    findings.append(finding)
    return finding


def text_for_ai(dictation_text: str) -> str:
    """El dictado sin los marcadores que se aplican por código (la IA no los ve)."""
    text = _SIDE_MARKER_RE.sub("", dictation_text)
    text = _DESCRIPTOR_MARKER_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extra_descriptions(dictation_text: str) -> List[str]:
    found = [m.group(1).strip() for m in _EXTRA_MARKER_RE.finditer(dictation_text)]
    found += [m.group(1).strip(" .") for m in _EXTRA_KEYWORD_RE.finditer(dictation_text)]
    out: List[str] = []
    for text in found:
        if text and not any(_score(text, seen) >= 0.6 for seen in out):
            out.append(text)
    return out


def _ensure_extra_findings(findings: List[Finding], dictation_text: str) -> None:
    for text in _extra_descriptions(dictation_text):
        if any(f.confirmed_line_id == EXTRA_ID and _score(f.description, text) >= 0.6 for f in findings):
            continue
        match = _best_match([f for f in findings if f.confirmed_line_id != EXTRA_ID], text)
        if match is None:
            match = _new_finding(findings, text)
        match.confirmed_line_id = EXTRA_ID
        match.status = "ACTIVE"
    for f in findings:
        if f.confirmed_line_id == EXTRA_ID and f.description:
            f.description = _EXTRA_PREFIX_RE.sub("", f.description)


def _apply_sides(findings: List[Finding], dictation_text: str) -> None:
    for m in _SIDE_MARKER_RE.finditer(dictation_text):
        raw = m.group(2).lower()
        side = "derecho" if raw.startswith("derech") else "izquierdo" if raw.startswith("izquierd") else "bilateral"
        target = _best_match(findings, m.group(1).strip()) or _new_finding(findings, m.group(1).strip())
        target.side = side


def _apply_descriptors(findings: List[Finding], dictation_text: str) -> None:
    grouped: dict = {}
    for m in _DESCRIPTOR_MARKER_RE.finditer(dictation_text):
        text, phrase = m.group(1).strip(), m.group(2).strip().rstrip(".")
        if not phrase:
            continue
        target = _best_match(findings, text) or _new_finding(findings, text)
        grouped.setdefault(id(target), (target, []))[1].append(phrase)
    for target, phrases in grouped.values():
        base = (target.description or target.name or "").strip().rstrip(" .,;")
        fresh: List[str] = []
        for phrase in phrases:
            if _norm(phrase) not in _norm(base) and phrase not in fresh:
                fresh.append(phrase)
        if not fresh:
            continue
        joined = fresh[0] if len(fresh) == 1 else ", ".join(fresh[:-1]) + " y " + fresh[-1]
        target.description = f"{base} con {joined}"


def finalize(
    findings: List[Finding],
    dictation_text: str,
    retry: Optional[Callable[[], List[Finding]]] = None,
) -> List[Finding]:
    """
    Aplica los marcadores sobre lo que devolvió el extractor. Si no devolvió
    nada pese a que el dictado tiene medidas, reintenta una vez y, si sigue
    vacío, falla con un error visible (nunca un informe vacío "Listo").
    """
    has_measure = bool(_MEASUREMENT_PATTERN.search(text_for_ai(dictation_text)))
    if not findings and has_measure and retry is not None:
        findings = retry()
    _ensure_extra_findings(findings, dictation_text)
    _apply_sides(findings, dictation_text)
    _apply_descriptors(findings, dictation_text)
    if not findings and has_measure:
        raise ValueError(
            "El extractor no devolvió hallazgos aunque el dictado tiene medidas. Probá de nuevo."
        )
    return findings
