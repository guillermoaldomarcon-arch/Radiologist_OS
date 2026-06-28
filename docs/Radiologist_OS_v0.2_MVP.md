# Radiologist_OS v0.2 — PROJECT SUMMARY (MVP-First)

> Este documento separa explícitamente dos capas:
> 1. **MVP REAL** — lo que se construye AHORA, esta semana/sprint.
> 2. **ROADMAP** — la visión completa, para contexto, pero NO para implementar todavía.
>
> Instrucción para Claude Code: trabajar **únicamente** sobre la sección MVP REAL.
> La sección ROADMAP es solo para entender el destino final, no es tarea pendiente.

---

## Objetivo del proyecto (visión completa, para contexto)

Radiologist_OS es un sistema operativo radiológico centrado en:

* Seguridad clínica por sobre velocidad.
* Principio de mínima modificación.
* Razonamiento fisiopatológico.
* Incertidumbre calibrada (nunca aumentar certeza artificialmente).
* Longitudinalidad (comparar al paciente consigo mismo, no con la población).
* Prevención de alucinaciones.
* El radiólogo humano es siempre la autoridad final.

Este proyecto es una evolución/refactor de DiagnosIA, llevando su lógica de razonamiento diagnóstico a una arquitectura más modular y trazable.

---

# 🚀 MVP REAL — Implementar ahora

## Alcance de este sprint

```text
Parser Engine → Finding objects → Template Engine → Quality Engine → Followup Engine → Report
```

**Explícitamente fuera de alcance en este sprint** (no generar código para esto todavía):
- Voice Engine (sin transcripción de audio — input es texto ya dictado/tipeado)
- Devil Advocate Engine
- World Model Engine
- Digital Twin Engine
- Meta Engine
- Ontología completa, RAG, integración RIS/PACS

## Input del MVP

Texto plano (dictado ya transcripto por el usuario o copiado), **no audio**.

## Pipeline del MVP

### 1. Parser Engine (`parser_engine.py`)

Convierte texto libre en objetos `Finding`. Reutiliza, en la medida de lo posible, lógica ya validada en DiagnosIA para extracción de hallazgos.

### 2. Template Engine (`template_engine.py`)

Genera el informe estructurado a partir de los `Finding` objects.

**Decisión de diseño clave**: los templates de Guille no comparten una estructura común entre especialidades/protocolos (confirmado — varía por modalidad y protocolo). Esto significa que el Template Engine **no puede tener templates hardcodeados en el código**. Debe ser un motor genérico que:

1. Carga una **definición de template** (qué secciones tiene, qué campos espera, en qué orden) desde un archivo de configuración (JSON o YAML) en `templates/`.
2. Mapea los `Finding` objects disponibles a esa definición.
3. Si la definición pide un campo/sección que no tiene `Finding` correspondiente, lo deja vacío o marcado como pendiente — **nunca inventa contenido para rellenar el template**.

Esto cumple el principio de mínima modificación: agregar un template nuevo en el futuro = agregar un archivo de definición, no tocar el motor.

**Formato de definición**: JSON (no YAML). Elegido por ser más robusto a errores de edición manual desde el editor web de GitHub, sin entorno local ni linter — los errores de sintaxis JSON (coma/llave faltante) son más fáciles de detectar a simple vista que problemas de indentación en YAML.

**Alcance MVP: motor genérico + 4 definiciones de template** (decidido con Guille — cobertura real de su variedad de protocolos, no simplificada a 3):

1. **Radiografía de tórax** (`templates/rx_torax.json`) — imagen simple, estructura más liviana.
2. **TC de cerebro** (`templates/tc_cerebro.json`) — estructura compleja, múltiples regiones/estructuras anatómicas.
3. **RM de columna** (`templates/rm_columna.json`) — estructura compleja, múltiples niveles vertebrales.
4. **Ecografía abdominal** (`templates/eco_abdominal.json`) — múltiples órganos por estudio (hígado, vesícula, páncreas, riñones, etc.), cada uno con sus propios hallazgos posibles.

Cada definición debe especificar, como mínimo:
- `modality`: string (ej: "RX", "TC", "RM", "ECO")
- `study_type`: string (ej: "torax", "cerebro", "columna", "abdominal")
- `sections`: lista ordenada de secciones del informe (ej: indicación, técnica, hallazgos por región/órgano, impresión)
- `expected_organs_or_regions`: lista controlada de órganos/regiones válidos para ese estudio (usada también por el Quality Engine, Capa 1, para validar que `Finding.organ` sea válido para el template usado)

Estas 4 definiciones son la prueba de que el motor generaliza correctamente antes de invertir en la librería completa. No construir las 50 templates todavía — eso queda en ROADMAP.

### 3. Quality Engine (`quality_engine.py`) — **especificación concreta**

Responsabilidad: detectar errores y posibles alucinaciones, **sin corregir nada automáticamente**. Si detecta un problema, marca el finding y bloquea la liberación del informe hasta revisión humana.

Funciona en 3 capas, cada una solo se activa si la anterior no encontró un bloqueo:

**Capa 1 — Validación estructural (determinística, sin llamadas a IA)**
- Medida sin unidad o con unidad fuera de un set válido (mm, cm).
- Contradicción de lateralidad dentro del mismo finding (`side` vs texto en `description`).
- `organ` fuera de una lista controlada según la modalidad/template usado.
- Finding duplicado (mismo organ + location + description).

**Capa 2 — Validación de coherencia clínica (un segundo llamado a Claude, acotado)**
Solo si Capa 1 no bloqueó nada. Se le pasa el `Finding` + el texto original dictado, con una pregunta cerrada y específica (no abierta):
> "¿Este finding está respaldado por el texto dictado? ¿Hay alguna medida, lateralidad o afirmación en el finding que no aparece en el texto original?"

**Capa 3 — Bloqueo, no autocorrección**
- Si Capa 1 o Capa 2 detectan un problema → `status: FLAGGED` + motivo registrado.
- Un informe con cualquier finding `FLAGGED` **no se libera automáticamente**. Requiere revisión y confirmación explícita del radiólogo.
- Nunca se modifica el finding de forma automática para "arreglar" el problema detectado.

### 4. Followup Engine (`followup_engine.py`)

Compara el informe actual contra historiales previos del mismo paciente (ya existentes en DiagnosIA/Supabase).

Clasifica cada finding relevante en:

```python
NEW
STABLE
PROGRESSIVE
RESOLVED
INDETERMINATE
```

**Alcance MVP**: comparación campo a campo (organ + location + size) contra el informe previo más reciente del mismo paciente. No implementar todavía el Digital Twin completo (perfil longitudinal multi-estudio, tendencias).

---

## Modelos a implementar (orden sugerido)

### `finding.py` — ✅ YA CREADO

```python
from dataclasses import dataclass
from typing import Optional


@dataclass
class Finding:
    """
    Fundamental radiological finding object.
    """
    name: str
    organ: Optional[str] = None
    location: Optional[str] = None
    side: Optional[str] = None
    size_mm: Optional[float] = None
    description: Optional[str] = None
    certainty: str = "MODERATE"
    status: str = "ACTIVE"
```

### `confidence.py` — próximo

```python
from enum import Enum

class Confidence(Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
```

### `status.py` — próximo

```python
from enum import Enum

class Status(Enum):
    ACTIVE = "ACTIVE"
    STABLE = "STABLE"
    NEW = "NEW"
    RESOLVED = "RESOLVED"
    CHRONIC = "CHRONIC"
    PROGRESSIVE = "PROGRESSIVE"
    FLAGGED = "FLAGGED"  # agregado para soportar el Quality Engine
```

### `recommendation.py` — próximo

Objeto `Recommendation` (campos a definir junto con `report.py`).

### `report.py` — próximo

```python
indication
technique
findings          # list[Finding]
impression
recommendations   # list[Recommendation]
warnings          # poblado por Quality Engine si hay FLAGGED findings
quality_score
confidence
status            # bloqueado si hay findings FLAGGED
```

---

## Tests mínimos requeridos en el MVP (no opcional)

No dejar los tests para "fase futura". Para un sistema que toca razonamiento diagnóstico, el MVP necesita desde el día uno:

- **1 caso de prueba real (anonimizado) por cada uno de los 4 templates** (Rx tórax, TC cerebro, RM columna, Eco abdominal) — texto dictado de entrada y el `Finding`/`Report` esperado como ground truth. Esto valida que el Template Engine generaliza de verdad entre estructuras distintas, no solo en el caso más simple.
- **Al menos 1 caso adversarial** (en cualquiera de los 4): un dictado con una medida inventada o contradicción de lateralidad deliberada, para confirmar que el Quality Engine la detecta y bloquea (no la corrige).
- **1 caso de Followup**: mismo paciente, dos estudios del mismo template, verificar que clasifica correctamente NEW/STABLE/PROGRESSIVE/RESOLVED.

---

## Principios críticos (aplican siempre, MVP y roadmap)

**Nunca:**
* inventar hallazgos
* inventar medidas
* transformar incertidumbre en certeza
* corregir automáticamente un finding marcado como problemático
* reemplazar al radiólogo

**Siempre:**
* preservar incertidumbre
* preservar significado original del dictado
* priorizar seguridad sobre velocidad
* mantener trazabilidad (qué motor tocó qué, y por qué)

---

# 🗺️ ROADMAP — Visión completa (NO implementar todavía)

Esta sección es para contexto y dirección a largo plazo. Claude Code no debe generar código para nada de lo siguiente hasta que se indique explícitamente.

## Engines futuros

* **Voice Engine** — normalización de dictado por voz (terminología médica, negaciones, lateralidad, incertidumbre). Requiere integración Whisper.
* **Devil Advocate Engine** — pregunta "¿y si estamos equivocados?", busca diagnósticos alternativos y sesgo de satisfacción de búsqueda. Nunca aumenta la confianza.
* **World Model Engine** — razonamiento causal (Patrón → Mecanismo → Enfermedades → Probabilidad → Peligros). No diagnostica automáticamente.

**Nota concreta (jun 2026, decisión explícita de Guille)**: dentro de este Devil Advocate/World Model Engine debe vivir la capacidad de que la IA *sugiera* (nunca inserte automáticamente) hallazgos asociados que el radiólogo podría haber omitido al dictar, basándose en correlación fisiopatológica real — ejemplo concreto discutido: un tumor con efecto de masa muy probablemente desvía la línea media y comprime el ventrículo adyacente; si el médico dictó el tumor pero no esos hallazgos asociados, el sistema debería señalarlo como sugerencia para que el médico lo confirme o descarte, no agregarlo por su cuenta. Esto es deliberadamente POSTERIOR a consolidar el MVP actual (extracción + reemplazo de líneas), porque es la pieza de mayor riesgo clínico del sistema: ya no es "¿transcribió bien lo que dije?" sino "¿está razonando correctamente sobre medicina sin sesgar al radiólogo?". Requiere diseño de seguridad propio antes de implementarse (ej. cómo se presenta visualmente una sugerencia vs. un hallazgo dictado, cómo se evita que el radiólogo "firme" sugerencias sin revisar a conciencia, etc.).
* **Digital Twin Engine** — perfil longitudinal completo del paciente consigo mismo (más allá de comparar el último estudio, como hace Followup Engine en el MVP).
* **Meta Engine** — orquestador final que integra calidad, incertidumbre, longitudinalidad, riesgos y diferenciales en el informe final.

## Otras expansiones futuras

* Template Library completa (meta: 50 templates — TC cerebro, TC tórax, TC abdomen, RM hombro, RM rodilla, ecografía abdomen, radiografía tórax, etc.)
* Ontología médica completa
* RAG sobre literatura/guías clínicas
* Benchmarks formales
* Integración RIS/PACS
* MCP

## Ideas adicionales incorporadas (origen: síntesis de visión elaborada en otra herramienta, jun 2026)

Estas ideas no añaden engines nuevos a la arquitectura ya definida arriba — se mapean sobre los engines existentes (Quality, Followup, Template) o son features de producto a futuro. Se listan aquí como inspiración para fases posteriores, no como tareas:

* **Checklist inteligente de omisiones**: que el sistema señale qué estructuras esperadas por el template (`expected_organs_or_regions`) NO fueron mencionadas en el dictado — ni como hallazgo ni como NO_FINDING — para ayudar a detectar olvidos antes de cerrar el informe. Esto es una extensión natural del Quality Engine ya existente, no un módulo nuevo.
* **Aprendizaje de estilo del radiólogo / personalización del lenguaje**: una vez que haya suficientes dictados reales calibrados (como los que ya fuimos incorporando a los templates), el sistema podría aprender preferencias de fraseo propias de Guille por tipo de estudio.
* **Auditoría de informes / estadísticas personales**: métricas agregadas sobre cuántos informes quedaron FLAGGED, qué tipo de issues son más frecuentes, etc. — útil una vez que haya volumen real de uso.
* **Protocolos dinámicos** (plantillas que omiten secciones sin hallazgos en vez de mostrar apartados vacíos): ya parcialmente cubierto por el diseño actual del Template Engine (no inventa contenido para rellenar), pero se podría refinar más adelante para que el informe final omita por completo secciones sin ningún Finding asociado, en vez de solo no inventarlas.
* **Expansión a otras especialidades** (cardiología, neumología, gastroenterología, medicina nuclear, patología): considerar solo después de que el MVP esté validado en uso real dentro de radiología.

## Integración con PACS/RIS — niveles de complejidad (no implementar todavía)

La integración con sistemas hospitalarios no es un solo paso — son niveles de complejidad creciente, y conviene no saltar etapas:

- **Nivel 0 (estado actual del MVP)**: sin integración. El radiólogo pega/escribe el dictado manualmente, recibe el informe. El PACS no participa.
- **Nivel 1 — datos del paciente (no imágenes)**: el RIS/PACS provee al sistema el informe previo del mismo paciente automáticamente (alimentando al Followup Engine sin copiar/pegar manual). Típicamente vía estándares **HL7** o **FHIR**.
- **Nivel 2 — imágenes (DICOM)**: el PACS envía las imágenes mismas en formato **DICOM** para que, en el futuro, un engine de visión (no existente hoy, sería parte de un futuro World Model Engine) las analice directamente, no solo el texto dictado.
- **Nivel 3 — escritura bidireccional**: el informe final generado se escribe automáticamente de vuelta al RIS/PACS (vía DICOM Structured Report o HL7), sin copiar/pegar manual del lado de salida.

**Recomendación de secuencia**: validar el Nivel 0 en uso real durante un tiempo antes de evaluar Nivel 1. Los niveles 2 y 3 dependen fuertemente de qué PACS/RIS específico use cada institución — no hay un único camino de integración válido para todos los casos.

---

# Instrucción para Claude Code

Trabajar como implementador del **MVP REAL** únicamente (sección de arriba). La sección ROADMAP es contexto, no tarea.

Prioridades, en este orden:
1. Seguridad clínica (nunca autocorregir, nunca inventar).
2. Tests primero — especialmente el caso adversarial de Quality Engine.
3. Código limpio y tipado fuerte.
4. Principio de mínima modificación.
5. Modularidad (cada engine independiente y testeable solo).
6. No sobreingeniería — si no está en MVP REAL, no se construye todavía.
7. Mantener trazabilidad.
8. El radiólogo humano es siempre la autoridad final.

---

## Estado actual

✅ Arquitectura completa definida (visión).
✅ Repositorio creado.
✅ 4 modelos implementados: `finding.py`, `confidence.py`, `status.py`, `recommendation.py`, `report.py`.
✅ 4 engines del MVP implementados: `parser_engine.py` (**v2**, ver más abajo), `template_engine.py`, `quality_engine.py`, `followup_engine.py`.
✅ 4 templates JSON creados y calibrados con dictados reales de Guille: `tc_cerebro.json` (**v2**, estructura de secciones/líneas fijas), `rx_torax.json`, `rm_columna.json`, `eco_abdominal.json` (estos 3 últimos siguen en formato v1 — lista plana de `expected_organs_or_regions`, sin `sections`/`lines`).
✅ `integrations/claude_client.py`: conexión real y portable a la API de Anthropic (modelo `claude-sonnet-4-6`), no solo simulada en tests.
✅ `run_pipeline_demo.py`: demo end-to-end del pipeline completo (basado en v1), con o sin API real (flag `--real`).
✅ `line_based_report_engine.py` (**nuevo**, ver más abajo): motor de reemplazo de líneas sobre plantilla normal.
✅ 6 tests creados y pasando (corren en modo offline/rules-only, siguen validando el comportamiento v1 retrocompatible): `test_templates.py` (13 checks), `test_quality_adversarial.py` (12 checks), `test_followup.py` (5 checks).

### ⚠️ Cambio de arquitectura — Parser Engine v2 (jun 2026)

A partir de un caso real de Guille ("lesión hipodensa paraventricular derecha de aspecto isquémico secuelar") que el parser v1 no pudo capturar — porque no contenía ninguna palabra de la lista fija de vocabulario, aunque es clínicamente un hallazgo inequívoco — se rediseñó el Parser Engine:

- **v1 (original)**: reglas primero, IA solo como fallback cuando las reglas no alcanzan. IA = certeza LOW automática.
- **v2 (actual)**: la IA es el mecanismo PRIMARIO de reconocimiento, usando conocimiento médico real (no una lista fija) para identificar hallazgos patológicos, incluyendo localizaciones indirectas ("paraventricular") y terminología descriptiva ("isquémico secuelar"). Las reglas pasan a un rol de **verificación posterior**: cada dato que la IA extrajo (medida, lateralidad) se confirma contra el texto literal del dictado. La certeza ya no depende de "vino de IA vs vino de reglas" — depende de si cada dato es verificable contra el texto original.
- El modo offline (`call_claude=None`) se conserva como fallback degradado solo para tests sin API — en ese modo, el sistema vuelve a las reglas v1 y NO puede reconocer patología descrita con vocabulario fuera de la lista fija. **Esto significa que para detectar patología real en producción, el sistema depende de tener `ANTHROPIC_API_KEY` configurada.**
- Bug corregido durante la calibración: la verificación de lateralidad fallaba por concordancia de género ("derecho" vs "derecha" en el texto real) — se corrigió comparando solo la raíz de la palabra.

### ⚠️ Nuevo módulo — Line-Based Report Engine (jun 2026)

Guille aclaró que su forma real de trabajo no es "construir un informe desde cero a partir de hallazgos", sino **editar un informe normal ya existente**, reemplazando solo las líneas afectadas por hallazgos patológicos, manteniendo intactas las líneas no mencionadas. Esto requirió:

- **Nuevo formato de template** (`tc_cerebro.json` ya migrado, los otros 3 templates pendientes de migrar): en vez de una lista plana de regiones, ahora tiene `sections` → cada sección tiene `lines` fijas, cada línea con `line_id`, `normal_text`, `concept` (descripción clínica para que la IA pueda mapear), y `omit_if_replaced_by_major_finding`.
- **`line_based_report_engine.py`**: la IA mapea cada hallazgo dictado a la línea de la plantilla que le corresponde (usando el campo `concept`), reemplazando esa línea específica. El orden final del informe SIEMPRE sigue el orden fijo de la plantilla, sin importar el orden en que se dictaron los hallazgos (validado explícitamente con test).
- **Regla de omisión — corregida durante el diseño**: inicialmente se diseñó para omitir una línea genérica de normalidad solo si el hallazgo era "grande/expansivo". Guille corrigió esto: la omisión es **mecánica y determinística** — cualquier hallazgo patológico (`ACTIVE`) en una sección invalida automáticamente las líneas de esa sección marcadas `omit_if_replaced_by_major_finding=true`, sin importar tamaño ni gravedad. Esto evita que la IA tenga que juzgar severidad, que es presición clínica que no debe delegarse a una heurística.
- **Seguridad preservada**: un hallazgo que la IA no puede mapear con confianza a ninguna línea NUNCA se descarta — aparece en una sección separada "HALLAZGOS SIN UBICAR" al final del informe, visible para revisión manual.
- Validado con el caso real completo de Guille (lesión tumoral talámica con efecto de masa) — el resultado generado coincide línea por línea con su informe final real.

⬜ **Pendiente — migrar los otros 3 templates** (`rx_torax.json`, `rm_columna.json`, `eco_abdominal.json`) al nuevo formato de `sections`/`lines`, siguiendo el patrón de `tc_cerebro.json`. Sin esto, `line_based_report_engine.py` solo funciona con TC cerebro.

⬜ **Pendiente — actualizar los 6 tests existentes** para reflejar el parser v2 y el line_based_report_engine (hoy siguen validando el comportamiento v1, que se mantiene como fallback offline, pero no cubren el camino AI-primario ni el nuevo motor de líneas).

⬜ **Pendiente — conexión real con la API**: todo lo construido hoy (parser v2, line_based_report_engine) depende de `call_claude` real para funcionar como está pensado. Sigue sin probarse con una `ANTHROPIC_API_KEY` real en un entorno real (ver Plan de próximos pasos).

**Decisiones de diseño previas que se mantienen** (del diseño v1, documentadas en el código):
- Negaciones generan Finding con `status="NO_FINDING"` en vez de ser descartadas — preserva trazabilidad de qué fue evaluado.
- Quality Engine: 3 capas (estructural → coherencia con IA → bloqueo). Nunca corrige automáticamente, solo marca `FLAGGED` con motivo.
- Followup Engine: umbral de cambio real = combinado, ≥3mm absoluto Y ≥20% relativo al tamaño previo (criterio tipo RECIST, decidido con Guille).

**Calibración con dictados reales — hallazgos del proceso**: al probar el parser v1 contra dictados reales de Guille (no inventados), se encontraron y corrigieron brechas reales de vocabulario y de patrones de negación en cada uno de los 4 templates — por ejemplo, "no se observan" (plural) no estaba cubierto, solo "no se observa" (singular); "uniforme" y "no evidencian" no estaban reconocidos como sinónimos de normalidad; "agujeros de conjunción" (término real usado) no coincidía con "forámenes de conjunción" (término que se había puesto inicialmente); "Ambos Riñones" (descripción conjunta) no coincidía con "riñón derecho"/"riñón izquierdo" (siempre separados). Esto confirmó que la calibración con dictados reales no es opcional. El mismo patrón se repitió al diseñar v2: el primer caso real probado ("lesión hipodensa paraventricular...") expuso que el enfoque de vocabulario fijo no escalaba a terminología patológica real, motivando el cambio de arquitectura.

## Plan de próximos pasos hacia uso diario (no implementado todavía)

Esto es lo que falta para pasar de "engines que funcionan en pruebas" a "herramienta usable en consultorio", en orden sugerido:

1. **Interfaz simple** (como ya existe para GuardIA/DiagnosIA): una página web donde Guille pueda pegar/escribir el dictado y obtener el informe, sin tocar código. No requiere todos los engines del MVP expuestos — alcanza con un endpoint que reciba texto + template_id y devuelva el Report.
2. **Despliegue en un servidor** (Railway, ya conocido): el código de Radiologist_OS no puede ejecutarse en el Windows 7 de Guille (Python moderno no es compatible). Necesita correr en un servicio remoto, igual que GuardIA hoy.
3. **Variable de entorno `ANTHROPIC_API_KEY` configurada en ese servidor**, para que `claude_client.py` funcione en producción, no solo en pruebas.
4. **Persistencia de informes** (conectar con Supabase, como ya tiene GuardIA): hoy cada `Report` vive solo en la memoria de una ejecución puntual. Para que el Followup Engine compare contra estudios previos reales, los informes anteriores necesitan guardarse en una base de datos.
5. **Decisión de producto**: ¿Radiologist_OS es una app nueva independiente, o un módulo dentro de DiagnosIA? Afecta cómo se organiza el despliegue y la autenticación de usuarios.
6. **Validación en uso real** durante un tiempo, antes de evaluar cualquier integración con PACS/RIS (ver sección de niveles más abajo).

🚀 Próximo paso concreto sugerido: punto 1 (interfaz simple) + punto 2 (despliegue), siguiendo el mismo patrón ya usado para GuardIA — esto es lo que primero convierte el proyecto en algo usable, antes de sumar persistencia o integraciones.

