"""
run_pipeline_demo.py

Demuestra el pipeline completo end-to-end:
Dictado -> Parser (reglas + IA) -> Template -> Quality -> Followup -> Report

En este demo, el dictado incluye una frase que las reglas del parser
NO pueden resolver por sí solas (sin medida, sin lateralidad clara,
sin negación reconocida) -- esto fuerza el uso del fallback de IA.

Para correr esto con la API real de Claude:
    pip install anthropic --break-system-packages
    export ANTHROPIC_API_KEY="sk-ant-..."
    python3 run_pipeline_demo.py --real

Sin el flag --real, usa una respuesta de IA simulada (para que se
pueda correr sin gastar API ni necesitar conexión).
"""

import sys
from parser_engine import parse
from template_engine import build_report, load_template
from quality_engine import apply_quality_check
from followup_engine import compare_reports


USE_REAL_API = "--real" in sys.argv


def get_call_claude():
    if USE_REAL_API:
        from claude_client import call_claude
        print(">>> Usando API REAL de Anthropic (claude-sonnet-4-6)\n")
        return call_claude
    else:
        print(">>> Usando respuesta de IA SIMULADA (sin API real, sin gastar tokens)\n")

        def fake_call_claude(prompt: str) -> str:
            # Distingue qué motor está llamando, según la forma del
            # prompt, y responde con el esquema JSON correcto para
            # cada caso. Esto es solo para la simulación del demo —
            # con --real, ambos prompts van a la API real y Claude
            # responde el esquema correcto porque cada engine se lo
            # pide explícitamente en su propio prompt.
            is_quality_layer_2 = "\"supported\": boolean" in prompt

            if is_quality_layer_2:
                # Capa 2 del Quality Engine: pregunta cerrada de
                # coherencia. Simulamos que todo lo que viene de
                # reglas (HIGH/MODERATE certainty, ya validado en
                # texto) está bien soportado, y solo objetamos si el
                # prompt menciona explícitamente el caso ambiguo.
                if "etiología incierta" in prompt:
                    return '{"supported": true, "reason": "Coincide con el texto original."}'
                return '{"supported": true, "reason": "Coincide con el texto original."}'

            # Parser Engine: fallback de extracción para una frase
            # que las reglas no pudieron resolver.
            if "etiología incierta" in prompt or "inespecífico" in prompt:
                return '''{
  "organ": "fosa posterior",
  "location": null,
  "side": null,
  "size_mm": null,
  "description": "Imagen hiperdensa de aspecto inespecífico en fosa posterior, de etiología incierta.",
  "present": true
}'''
            return '{"present": false, "description": ""}'

        return fake_call_claude


def run_dictation(dictado: str, template_id: str, indication: str, call_claude):
    print(f"--- DICTADO ({template_id}) ---")
    print(dictado.strip())
    print()

    template = load_template(template_id)

    findings = parse(
        dictado,
        call_claude=call_claude,
        organ_hints=template["expected_organs_or_regions"],
    )

    print(f"FINDINGS EXTRAÍDOS ({len(findings)}):")
    for f in findings:
        print(
            f"  - organ={f.organ!r} status={f.status} certainty={f.certainty} "
            f"size_mm={f.size_mm} side={f.side}"
        )
    print()

    issues = apply_quality_check(
        findings,
        expected_organs_or_regions=template["expected_organs_or_regions"],
        original_text=dictado,
        call_claude=call_claude,
    )

    print(f"QUALITY ENGINE — issues detectados: {len(issues)}")
    for issue in issues:
        print(f"  - [Layer {issue.layer}] {issue.finding.organ}: {issue.reason}")
    print()

    report = build_report(
        findings=findings, template_id=template_id, indication=indication
    )
    report.recompute_status()

    print("REPORTE FINAL:")
    print(f"  Indicación: {report.indication}")
    print(f"  Técnica:    {report.technique}")
    print(f"  Impresión:")
    print("   ", report.impression.replace("\n", "\n    "))
    print(f"  Status:     {report.status}")
    print(f"  ¿Liberable? {report.is_releasable()}")
    if report.warnings:
        print(f"  Warnings:   {report.warnings}")
    print()

    return report


if __name__ == "__main__":
    call_claude = get_call_claude()

    print("=" * 70)
    print("DEMO: pipeline completo con caso que requiere fallback de IA")
    print("=" * 70)
    print()

    dictado = """
Técnica: TC de cerebro sin contraste, cortes axiales.
Parénquima cerebral con hipodensidad de 15 mm a nivel de la región frontal derecha.
Ventrículos de tamaño y morfología conservados.
Cisterna basal sin alteraciones.
Se observa una imagen hiperdensa de aspecto inespecífico en fosa posterior, de etiología incierta.
"""

    report = run_dictation(
        dictado=dictado,
        template_id="tc_cerebro",
        indication="Cefalea de reciente comienzo, descartar lesión estructural.",
        call_claude=call_claude,
    )

    print("=" * 70)
    print(
        "NOTA: el finding de 'fosa posterior' vino del FALLBACK DE IA "
        "(las reglas no detectaron medida, lateralidad ni negación en "
        "esa frase). Por eso quedó con certainty=LOW automáticamente."
    )
    print("=" * 70)
