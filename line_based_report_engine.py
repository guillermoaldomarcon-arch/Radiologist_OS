def _group_finding_indices_by_line(matches: list) -> dict:
    grouped: dict = {}
    for match in matches:
        line_id = match.get("line_id")
        finding_index = match.get("finding_index")
        if line_id is None or finding_index is None:
            continue
        grouped.setdefault(line_id, []).append(finding_index)
    return grouped


def _composed_line_contradicts_bilateral_normal(
    normal_text: str, composed_line: str, findings_for_line: List[Finding]
) -> bool:
    """
    Chequeo mecanico (no IA): si el texto normal de la linea es bilateral
    ("ambos X normales") y algun hallazgo mapeado a esa linea tiene
    lateralidad explicita, la oracion compuesta NO puede seguir
    conteniendo una afirmacion bilateral generica -- eso es exactamente
    la contradiccion vista en produccion ("ambos rinones normales" +
    masa unilateral en el mismo parrafo). No decide contenido clinico,
    solo decide si confiar en la composicion de la IA o fallar visible.
    """
    normal_lower = normal_text.lower()
    composed_lower = composed_line.lower()

    is_bilateral_normal_line = "ambos" in normal_lower or "bilateral" in normal_lower
    has_lateralized_finding = any(f.side for f in findings_for_line)

    return is_bilateral_normal_line and has_lateralized_finding and "ambos" in composed_lower
