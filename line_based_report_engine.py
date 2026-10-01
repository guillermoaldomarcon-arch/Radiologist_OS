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

The AI is used to do the matching AND the composition: given the
full set of normal lines (each with its `concept`) and the dictated
pathological findings, it decides which line_id each finding
corresponds to, and composes the final sentence for each affected
line, preserving whatever part of the normal text isn't contradicted
by the dictated findings.

Safety principles preserved:
- The AI NEVER invents a finding not in the dictation; it only maps
  EXISTING dictated findings (already extracted by parser_engine) to
  template line_ids, and composes sentences strictly from those
  findings plus the template's own normal text.
- If the AI cannot confidently map a finding to any line_id, that
  finding is NOT silently dropped -- it's appended in a clearly
  marked section so the radiologist sees it and can place it
  manually. This is a deliberate "fail visibly, not silently" choice.
- Multiple findings mapped to the SAME line are never silently
  overwritten -- they are all folded into one composed sentence.
- Order of dictation does NOT determine order in the final report --
  the final report always follows the template's fixed line order,
  per Guille's explicit requirement that this must work regardless
  of dictation order.
- BILATERAL LINES (2026-09-26 redesign): lines whose normal_text says
  "ambos"/"bilateral" are no longer composed by the AI at all --
  composition for these is fully mechanical/deterministic (see
  _compose_bilateral_line), general to ANY template that uses that
  wording, without needing per-template changes (e.g. splitting
  "rinones" into rinon_derecho/rinon_izquierdo). Retired approach:
  an earlier version asked Claude to compose these lines and only
  checked AFTER the fact whether it still said "ambos" while a
  lateralized finding was present (_composed_line_contradicts_
  bilateral_normal, removed). That caught the one-sided contradiction
  case but still relied on the AI, and did not handle the case where
  BOTH sides were dictated explicitly (seen in production 2026-09-26:
  a bilateral pathological finding with both measurements ended up
  entirely unmatched, leaving a false "ambos rinones normales" line
  in the report).
- CORRECTION (2026-09-26, same day): the first version of the
  deterministic bilateral composer built each side's sentence from
  Finding.description alone, assuming side/size_mm would already be
  embedded in the free-text description. That held for one tested
  case (bazo) but not for another (rinones dictados como "el derecho
  mide 85 mm y el izquierdo mide 80 mm"), where parser_engine
  correctly captured side/size_mm as structured fields but left
  description as just the qualifier ("disminuido de tamaño..."),
  with no subject or measurement in the free text at all -- producing
  a sentence with neither. Fixed by building each side's sentence
  explicitly from organ + side + description + size_mm (see
  _sentence_for_side) instead of trusting description to be
  self-contained.
- A second mechanical safety check runs after composition -- if a
  finding mapped to a line has a confirmed size_mm, the composed
  sentence must literally contain that number. If Claude (or the
  bilateral composer) drops a confirmed measurement (seen in
  production: Regla B del abogado del diablo confirma una medida,
  pero la oracion final no la menciona), the composition is not
  trusted; the finding is treated as unmatched instead of silently
  losing clinical data the radiologist explicitly confirmed.
"""

import json
import re
from typing import Callable, List, Optional

from finding import Finding

_MM_IN_TEXT_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*mm\b", re.IGNORECASE)

_SIDE_MAP = {
    "derecho": "derecho", "derecha": "derecho", "der": "derecho", "right": "derecho",
    "izquierdo": "izquierdo", "izquierda": "izquierdo", "izq": "izquierdo", "left": "izquierdo",
    "bilateral": "bilateral", "bilaterales": "bilateral", "ambos": "bilateral",
}


def _capitalize_first(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    return text[0].upper() + text[1:]


def _normalize_side(side: Optional[str]) -> Optional[str]:
    if not side:
        return None
    return _SIDE_MAP.get(side.strip().lower())


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
                    "concept": line["concept"], "optional": line.get("optional", False),
                    "normal_text": line["normal_text"],
                    "omit_if_replaced_by_major_finding": line.get(
                        "omit_if_replaced_by_major_finding", False
                    ),
                }
            )
    return flat_lines


def _group_finding_indices_by_line(matches: list) -> dict:
    grouped: dict = {}
    for match in matches:
        line_id = match.get("line_id")
        finding_index = match.get("finding_index")
        if line_id is None or finding_index is None:
            continue
        grouped.setdefault(line_id, []).append(finding_index)
    return grouped


def _is_bilateral_normal_line(normal_text: str) -> bool:
    normal_lower = normal_text.lower()
    return "ambos" in normal_lower or "bilateral" in normal_lower


def _sentence_for_side(
    organ_name: Optional[str], side_label: Optional[str], findings: List[Finding]
) -> Optional[str]:
    """
    Arma la oracion para un lado (o para un hallazgo ya dictado como
    bilateral, con side_label=None) usando los campos ESTRUCTURADOS
    del Finding (organ, side, size_mm), no solo el texto libre de
    description. Necesario porque description puede venir sin sujeto
    ni medida cuando el medico dicto la lateralidad y el numero por
    separado del hallazgo en si (ej: "el derecho mide 85 mm" dicho
    aparte de "disminuidos de tamaño de aspecto hipotroficos") -- ver
    nota de correccion en el docstring del modulo.
    """
    if not findings:
        return None

    parts = []
    for f in findings:
        desc = (f.description or f.name or "").strip().rstrip(".")
        if f.size_mm is not None and not _MM_IN_TEXT_PATTERN.search(desc):
            try:
                size_str = f"{float(f.size_mm):g} mm"
            except (TypeError, ValueError):
                size_str = None
            if size_str:
                desc = f"{desc}{_mide_clause(desc, size_str)}" if desc else f"mide {size_str}"
        if desc:
            parts.append(desc)

    body = "; ".join(parts)
    if not body:
        return None

    if organ_name and side_label:
        subject = f"{_capitalize_first(organ_name)} {side_label}"
        return _subject_sentence(organ_name, side_label, body)
    if organ_name:
        return _subject_sentence(organ_name, None, body)
    return _capitalize_first(body) + "."
_MIDE_PLURAL_HEADS = {
    "masas", "quistes", "nodulos", "polipos", "calculos", "abscesos", "tumores",
    "imagenes", "litos", "placas", "diverticulos", "ganglios", "hematomas",
    "lesiones", "calcificaciones", "adenopatias", "pliegues",
}


def _mide_clause(text: str, size_str: str) -> str:
    """", que mide X" / ", que miden X" según el texto hable de 'paredes' u otro plural."""
    plain = text.lower().translate(str.maketrans("áéíóú", "aeiou"))
    words = re.findall(r"[a-zñ]+", plain)
    plural = "paredes" in words or (bool(words) and words[0] in _MIDE_PLURAL_HEADS)
    return f", que miden {size_str}" if plural else f", que mide {size_str}"
    text = f"{text}{_mide_clause(text, size_str)}" if text else f"mide {size_str}"
_LINK_VERB_NOUNS = {
    "masa", "masas", "quiste", "quistes", "nodulo", "nodulos", "polipo", "polipos",
    "calculo", "calculos", "absceso", "abscesos", "tumor", "tumores", "imagen",
    "imagenes", "liquido", "barro", "lito", "litos", "trombo", "placa", "placas",
    "diverticulo", "diverticulos", "ganglio", "ganglios", "aneurisma", "edema",
    "hematoma", "hematomas", "aumento", "aumentos",
}
_LINK_VERB_SUFFIXES = (
    "cion", "ciones", "sion", "siones", "miento", "mientos", "dad", "dades",
    "ia", "itis", "osis", "iasis", "oma", "omas",
)


def _link_verb(text: str, organ: Optional[str], organ_present: bool) -> str:
    """
    " presenta" / " presentan" cuando hay que anteponer el órgano y el hallazgo
    arranca con un sustantivo ("Riñón derecho masa sólida" queda telegráfico).
    Vacío con participios, adjetivos o preposiciones ("disminuido de tamaño",
    "con masa..."), donde agregar el verbo sonaría mal.
    """
    if not organ or organ_present:
        return ""
    plain = text.strip().lower().translate(str.maketrans("áéíóú", "aeiou"))
    first = plain.split(" ")[0].strip(",.;:") if plain else ""
    if not first:
        return ""
    if first not in _LINK_VERB_NOUNS and not first.endswith(_LINK_VERB_SUFFIXES):
        return ""
    organ_words = organ.strip().lower().translate(str.maketrans("áéíóú", "aeiou")).split()
    last = organ_words[-1] if organ_words else ""
    plural = last.endswith(("es", "os", "as")) and last not in ("pancreas", "tiroides")
    return " presentan" if plural else " presenta"


def _lower_first(text: str) -> str:
    if len(text) > 1 and text[0].isupper() and not text[1].isupper():
        return text[0].lower() + text[1:]
    return text


_ACCENTS = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")


def _subject_sentence(organ_name: Optional[str], side_label: Optional[str], body: str) -> str:
    """
    Antepone órgano y lado al hallazgo SOLO si el texto del hallazgo no los
    menciona ya. Evita "Riñón derecho Riñón derecho de 85 mm..." cuando el
    parser trae la descripción completa. Mismo criterio que
    _describe_finding_for_impression en devil_advocate_engine.py.
    """
    body_norm = body.lower().translate(_ACCENTS)
    organ_norm = (organ_name or "").lower().translate(_ACCENTS)
    organ_present = bool(organ_norm) and organ_norm in body_norm
    side_present = bool(side_label) and side_label.rstrip("o") in body_norm

    if organ_present and side_label and not side_present:
        return f"{_capitalize_first(body)}, del lado {side_label}."

    parts = []
    if organ_name and not organ_present:
        parts.append(_capitalize_first(organ_name))
    if side_label and not side_present:
        parts.append(side_label)
    if not parts:
        return _capitalize_first(body) + "."

    if len(body) > 1 and body[0].isupper() and not body[1].isupper():
        body = body[0].lower() + body[1:]
    return f"{' '.join(parts)}{_link_verb(body, organ_name, organ_present)} {body}."


def _compose_bilateral_line(
    normal_text: str, findings_for_line: List[Finding]
) -> Optional[str]:
    """
    Composicion deterministica (sin IA) para lineas de plantilla
    bilaterales -- ver nota en el docstring del modulo. Regla general,
    aplicable a cualquier template que use "ambos"/"bilateral" en su
    normal_text, sin necesidad de tocar el JSON de la plantilla:

    - Si los hallazgos mapeados a esta linea mencionan un solo lado
      (derecho O izquierdo, nunca los dos), se arma la oracion para
      ese lado (organo + side + hallazgo + medida) + una oracion fija
      para el lado contralateral: "[Organo] contralateral es de
      morfologia y tamaño normal."
    - Si los hallazgos cubren ambos lados de forma explicita (derecho
      Y izquierdo dictados por separado), se arma una oracion por
      lado, sin agregar relleno.
    - Si un hallazgo ya viene marcado como side="bilateral" (el medico
      dicto explicitamente que afecta a ambos lados), se usa ese
      texto directo, sin agregar nada.
    - Si la linea no es bilateral, o hay lateralidad ambigua/faltante
      que no permite resolverlo con confianza, devuelve None -- el
      llamador debe tratar los hallazgos de esa linea como no
      ubicados en vez de arriesgar una redaccion incorrecta.
    """
    if not _is_bilateral_normal_line(normal_text):
        return None

    by_side: dict = {"derecho": [], "izquierdo": [], "bilateral": []}
    for f in findings_for_line:
        side = _normalize_side(f.side)
        if side is None:
            # Hallazgo mapeado a una linea bilateral sin lateralidad
            # reconocible -- no hay forma confiable de saber si cubre
            # un lado, el otro, o ambos. Fallar visible.
            return None
        by_side[side].append(f)

    organ_name = next((f.organ.strip() for f in findings_for_line if f.organ), None)

    if by_side["bilateral"]:
        if by_side["derecho"] or by_side["izquierdo"]:
            # Mezcla rara: un hallazgo dictado como "bilateral" y
            # ademas otro lateralizado por separado en la misma linea.
            # Ambiguo -- no combinar a ciegas, fallar visible.
            return None
        return _sentence_for_side(organ_name, None, by_side["bilateral"])

    sentences = []
    for side in ("derecho", "izquierdo"):
        side_findings = by_side[side]
        if side_findings:
            sentence = _sentence_for_side(organ_name, side, side_findings)
            if not sentence:
                return None
            sentences.append(sentence)
        else:
            if not organ_name:
                return None
            sentences.append(
                f"{_capitalize_first(organ_name)} contralateral es de morfología y tamaño normal."
            )

    return " ".join(sentences)


def _composed_line_missing_confirmed_measurement(
    composed_line: str, findings_for_line: List[Finding]
) -> bool:
    """
    Chequeo mecanico (no IA): si algun hallazgo mapeado a esta linea
    tiene una medida confirmada (size_mm), la oracion compuesta DEBE
    mencionar ese numero explicitamente (formato "X mm"). Visto en
    produccion: Claude recibe size_mm=17 en el prompt de composicion
    pero redacta la oracion sin incluirlo -- una medida que el medico
    confirmo explicitamente via Regla B no puede desaparecer en
    silencio. Si esto dispara, la linea se trata como no mapeada para
    que el medico la vea y la complete a mano, en vez de publicar un
    informe con una medida confirmada pero ausente.
    """
    sizes_in_text = set()
    for raw in _MM_IN_TEXT_PATTERN.findall(composed_line):
        try:
            sizes_in_text.add(round(float(raw.replace(",", ".")), 1))
        except ValueError:
            continue

    for f in findings_for_line:
        if f.size_mm is None:
            continue
        try:
            expected = round(float(f.size_mm), 1)
        except (TypeError, ValueError):
            continue
        if expected not in sizes_in_text:
            return True
    return False


def _compose_confirmed_line(
    line_id: str, findings_for_line: List[Finding], normal_text: str
) -> Optional[str]:
    """
    Compone una linea cuyo destino ya fue confirmado explicitamente por
    el medico (Finding.confirmed_line_id), sin pasar por Claude para el
    matching -- el "donde" ya no es una decision de la IA. La redaccion
    en si reusa la misma composicion deterministica que ya existe para
    bilaterales, y el mismo builder de oracion (_sentence_for_side) para
    el caso no-bilateral, para no duplicar la logica de inyeccion de
    size_mm ya probada.
    """
    bilateral_line = _compose_bilateral_line(normal_text, findings_for_line)
    if bilateral_line is not None:
        if _composed_line_missing_confirmed_measurement(bilateral_line, findings_for_line):
            return None
        return bilateral_line

    if _is_bilateral_normal_line(normal_text):
        # Bilateral pero no resoluble con confianza (mismo criterio que
        # el resto del modulo) -- no forzar una redaccion dudosa.
        return None

    composed = _sentence_for_side(None, None, findings_for_line)
    if not composed:
        return None
    if _composed_line_missing_confirmed_measurement(composed, findings_for_line):
        return None
    return composed


def _match_via_claude(
    findings: List[Finding],
    flat_lines: List[dict],
    call_claude: Callable[[str], str],
) -> dict:
    """
    Logica de matching+composicion por IA -- identica a la version
    anterior de _match_findings_to_lines, ahora aislada para poder
    correr solo sobre los findings que NO tienen confirmed_line_id.
    Los indices en el resultado son relativos a la lista `findings`
    que se le pasa, no a la lista original completa -- el llamador
    (_match_findings_to_lines) es responsable de traducirlos de vuelta.
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

    prompt = f"""Tenés una plantilla de informe radiológico normal, compuesta por líneas fijas, y una lista de hallazgos patológicos ya extraídos de un dictado. Tu tarea tiene dos partes.

PARTE 1 -- MATCHING: para cada hallazgo, decidí a qué línea de la plantilla corresponde clínicamente (qué línea normal ese hallazgo patológico afecta), usando tu conocimiento médico real. Puede haber MÁS DE UN hallazgo para la misma línea (ej: "paredes engrosadas" y "litiasis" pueden ser dos hallazgos distintos que afectan ambos a la línea de la vesícula) -- NUNCA descartes un hallazgo solo porque otro ya fue asignado a la misma línea.

PARTE 2 -- COMPOSICIÓN: para cada línea que recibió uno o más hallazgos, redactá la oración final que reemplaza el texto normal de esa línea, siguiendo estas reglas estrictas:
- Conservá TEXTUALMENTE (o casi textualmente, ajustando solo la gramática para que la oración quede coherente) cualquier atributo del texto normal original que NINGÚN hallazgo contradiga (ej: si el texto normal dice "forma y tamaño normal" y ningún hallazgo dictado menciona forma ni tamaño, esa parte se mantiene).
- Reemplazá o agregá ÚNICAMENTE los atributos que los hallazgos dictados mencionan explícitamente.
- REGLA OBLIGATORIA E INNEGOCIABLE: si un hallazgo tiene un valor de size_mm distinto de null, la oración compuesta DEBE incluir ese número explícitamente, en formato "X mm" (ej: size_mm=17 -> la oración debe contener literalmente "17 mm" en algún punto). Esto es obligatorio incluso si te parece redundante o si ya mencionaste el tamaño de otra forma -- el número en milímetros tiene que estar presente sí o sí.
- Si hay más de un hallazgo para la misma línea, integralos TODOS en una sola oración coherente, y aplicá la regla de arriba para CADA size_mm presente.
- NUNCA agregues ningún dato clínico, medida, lateralidad o hallazgo que no esté presente en los hallazgos dictados. No aumentes ni disminuyas certeza. Si tenés dudas sobre cómo integrar un atributo, priorizá conservar el texto normal antes que inventar redacción clínica no dictada.
- Mantené el mismo registro y estilo que el texto normal original de esa línea.

LÍNEAS DE LA PLANTILLA:
{lines_text}

HALLAZGOS DICTADOS (ya extraídos, NO los modifiques ni inventes otros):
{findings_text}

Respondé ÚNICAMENTE con un objeto JSON con esta forma exacta:

{{
  "matches": [
    {{"finding_index": int, "line_id": string}}
  ],
  "composed_lines": [
    {{"line_id": string, "composed_line": string}}
  ],
  "unmatched_finding_indices": [int]
}}

Donde:
- "matches": para cada hallazgo que SÍ corresponde claramente a una línea, indicá su índice y el line_id que afecta. Un mismo line_id puede aparecer en más de un match.
- "composed_lines": una entrada por cada line_id presente en "matches", con la oración final ya redactada según las reglas de la PARTE 2.
- "unmatched_finding_indices": índices de hallazgos que NO podés mapear con confianza a ninguna línea -- NUNCA fuerces un mapeo dudoso, es preferible dejarlo sin mapear.

No incluyas texto adicional, solo el JSON."""

    max_attempts = 2
    data = None

    for attempt in range(1, max_attempts + 1):
        current_prompt = prompt
        if attempt > 1:
            current_prompt = (
                prompt
                + "\n\nIMPORTANTE: tu respuesta anterior no era JSON valido. "
                "Respondio de nuevo, UNICAMENTE con JSON valido y bien formado: "
                "cada elemento de \"matches\" debe ser un objeto con comillas "
                "dobles en todas las claves y en todos los valores string, "
                "por ejemplo {\"finding_index\": 1, \"line_id\": \"bazo\"}. "
                "No omitas llaves, comillas ni comas en ningun elemento del array."
            )

        raw_response = call_claude(current_prompt)

        print(f"=== DEBUG_MATCH intento {attempt}: hallazgos enviados a Claude ===")
        print(findings_text)
        print(f"=== DEBUG_MATCH intento {attempt}: respuesta cruda de Claude ===")
        print(raw_response)
        print("=== FIN DEBUG_MATCH ===")

        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
                cleaned = cleaned.replace("json", "", 1).strip()
            data = json.loads(cleaned)
            break
        except (json.JSONDecodeError, AttributeError):
            print(f"=== DEBUG_MATCH intento {attempt}: JSON invalido, {'reintentando' if attempt < max_attempts else 'sin mas intentos'} ===")
            data = None
            continue

    if data is None:
        return {"_unmatched": list(range(len(findings)))}

    matched_line_ids = set()
    matched_indices = set()
    for match in data.get("matches", []):
        line_id = match.get("line_id")
        finding_index = match.get("finding_index")
        if line_id is not None and finding_index is not None:
            matched_line_ids.add(line_id)
            matched_indices.add(finding_index)

    composed_by_line_id = {}
    for entry in data.get("composed_lines", []):
        line_id = entry.get("line_id")
        composed_line = entry.get("composed_line")
        if line_id is not None and composed_line:
            composed_by_line_id[line_id] = composed_line

    line_id_to_normal_text = {l["line_id"]: l["normal_text"] for l in flat_lines}
    indices_by_line_id = _group_finding_indices_by_line(data.get("matches", []))

    result = {}
    contradicted_indices = set()

    for line_id in matched_line_ids:
        indices_for_line = indices_by_line_id.get(line_id, [])
        findings_for_line = [findings[i] for i in indices_for_line if 0 <= i < len(findings)]
        normal_text = line_id_to_normal_text.get(line_id, "")

        bilateral_line = _compose_bilateral_line(normal_text, findings_for_line)
        if bilateral_line is not None:
            if _composed_line_missing_confirmed_measurement(bilateral_line, findings_for_line):
                print(f"=== DEBUG_MATCH: linea '{line_id}' (bilateral) descartada por medida confirmada ausente en: {bilateral_line!r} ===")
                contradicted_indices.update(indices_for_line)
                continue
            result[line_id] = {"action": "replace", "composed_line": bilateral_line}
            continue

        if _is_bilateral_normal_line(normal_text):
            print(f"=== DEBUG_MATCH: linea '{line_id}' (bilateral) no resoluble, hallazgos sin ubicar ===")
            contradicted_indices.update(indices_for_line)
            continue

        composed_line = _sentence_for_side(None, None, findings_for_line) if any(l["line_id"] == line_id and l.get("optional") for l in flat_lines) else composed_by_line_id.get(line_id)

        if composed_line and _composed_line_missing_confirmed_measurement(
            composed_line, findings_for_line
        ):
            print(f"=== DEBUG_MATCH: linea '{line_id}' descartada por medida confirmada ausente en: {composed_line!r} ===")
            contradicted_indices.update(indices_for_line)
            continue

        if composed_line:
            result[line_id] = {"action": "replace", "composed_line": composed_line}
        else:
            fallback_text = "; ".join(
                findings[i].description for i in indices_for_line
                if 0 <= i < len(findings)
            )
            result[line_id] = {"action": "replace", "composed_line": fallback_text}

    all_indices = set(range(len(findings)))
    truly_unmatched = (all_indices - matched_indices) | contradicted_indices
    result["_unmatched"] = sorted(truly_unmatched)

    return result


def _match_findings_to_lines(
    findings: List[Finding],
    flat_lines: List[dict],
    call_claude: Callable[[str], str],
) -> dict:
    """
    Punto de entrada principal. Separa los findings en dos grupos antes
    de decidir ubicacion:

    1. Los que ya tienen Finding.confirmed_line_id (el medico ya
       confirmo explicitamente, via chip/marcador UBICACION_CONFIRMADA,
       a que linea van) -- se ubican directo, SIN pasar por Claude para
       el matching. El grupo de aprendizaje automatico (Regla de
       placement aprendido via Postgres) todavia no esta implementado
       -- queda pendiente, se sumara aca como un tercer grupo.
    2. El resto -- sigue el flujo de matching por IA de siempre
       (_match_via_claude), sin cambios de comportamiento.

    Los indices en el resultado final son SIEMPRE relativos a la lista
    `findings` original completa, sin importar por cual de los dos
    caminos paso cada uno.
    """
    if not findings:
        return {"_unmatched": []}

    line_id_to_normal_text = {l["line_id"]: l["normal_text"] for l in flat_lines}
    valid_line_ids = set(line_id_to_normal_text)

    confirmed_indices_by_line: dict = {}
    remaining_indices: List[int] = []

    for i, f in enumerate(findings):
        if f.confirmed_line_id and f.confirmed_line_id in valid_line_ids:
            confirmed_indices_by_line.setdefault(f.confirmed_line_id, []).append(i)
        else:
            remaining_indices.append(i)

    result: dict = {}
    contradicted_indices = set()
    resolved_confirmed_indices = set()

    for line_id, indices in confirmed_indices_by_line.items():
        findings_for_line = [findings[i] for i in indices]
        normal_text = line_id_to_normal_text[line_id]
        composed = _compose_confirmed_line(line_id, findings_for_line, normal_text)
        if composed is None:
            print(f"=== DEBUG_MATCH: linea '{line_id}' confirmada explicitamente pero no se pudo componer, queda sin ubicar ===")
            contradicted_indices.update(indices)
            continue
        result[line_id] = {"action": "replace", "composed_line": composed}
        resolved_confirmed_indices.update(indices)

    # El resto (findings sin confirmed_line_id valido, mas los que
    # quedaron contradichos arriba) va a Claude como antes. Los indices
    # que Claude devuelve son relativos a `remaining_findings`, hay que
    # traducirlos de vuelta a los indices reales de `findings`.
    truly_remaining = [
        i for i in remaining_indices if i not in resolved_confirmed_indices
    ] + sorted(contradicted_indices)
    truly_remaining = sorted(set(truly_remaining))

    remaining_findings = [findings[i] for i in truly_remaining]
    local_to_global = {local: global_i for local, global_i in enumerate(truly_remaining)}

    claude_result = _match_via_claude(remaining_findings, flat_lines, call_claude)

    for line_id, entry in claude_result.items():
        if line_id == "_unmatched":
            continue
        # composed_line ya viene armado; no hay indices que traducir aca,
        # pero si dos grupos (confirmado + IA) mapearan a la MISMA linea
        # en el mismo request (caso raro, pero posible), no sobreescribir
        # silenciosamente -- avisar.
        if line_id in result:
            print(f"=== DEBUG_MATCH: linea '{line_id}' recibida tanto por confirmacion explicita como por matching de Claude en el mismo request -- se prioriza la confirmacion explicita ===")
            continue
        result[line_id] = entry

    global_unmatched = [local_to_global[i] for i in claude_result.get("_unmatched", [])]
    result["_unmatched"] = sorted(global_unmatched)

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
                section_lines.append(action_entry["composed_line"])
                continue

            omit_if_major = line.get("omit_if_replaced_by_major_finding", False)
            if line.get("optional", False) or (omit_if_major and section_has_finding):
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

_ANY_MEASUREMENT_PATTERN = re.compile(r"\d+(?:[.,]\d+)?\s*(mm|cm)\b", re.IGNORECASE)


def _describe_unmatched_finding(f: Finding) -> str:
    """
    Texto de un hallazgo sin ubicar para el informe: descripcion + la
    medida confirmada (size_mm) si esa medida no esta ya escrita en la
    descripcion. Mismo criterio que _sentence_for_side.
    """
    desc = (f.description or f.name or "").strip().rstrip(".")
    if f.size_mm is not None and not _ANY_MEASUREMENT_PATTERN.search(desc):
        try:
            size_str = f"{float(f.size_mm):g} mm"
        except (TypeError, ValueError):
            size_str = None
        if size_str:
            desc = f"{desc}{_mide_clause(desc, size_str)}" if desc else f"mide {size_str}"
    return desc


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
            lines_out.append(f"\u00b7        {_describe_unmatched_finding(f)}")
        lines_out.append("")

    return "\n".join(lines_out)
