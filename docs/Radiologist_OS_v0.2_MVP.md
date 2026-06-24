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
* **Digital Twin Engine** — perfil longitudinal completo del paciente consigo mismo (más allá de comparar el último estudio, como hace Followup Engine en el MVP).
* **Meta Engine** — orquestador final que integra calidad, incertidumbre, longitudinalidad, riesgos y diferenciales en el informe final.

## Otras expansiones futuras

* Template Library completa (meta: 50 templates — TC cerebro, TC tórax, TC abdomen, RM hombro, RM rodilla, ecografía abdomen, radiografía tórax, etc.)
* Ontología médica completa
* RAG sobre literatura/guías clínicas
* Benchmarks formales
* Integración RIS/PACS
* MCP

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
✅ 4 engines del MVP implementados y validados: `parser_engine.py`, `template_engine.py`, `quality_engine.py`, `followup_engine.py`.
✅ 4 templates JSON creados: `tc_cerebro.json`, `rx_torax.json`, `rm_columna.json`, `eco_abdominal.json`.
✅ 6 tests creados y pasando: `test_templates.py` (1 caso por template, 13 checks), `test_quality_adversarial.py` (3 casos adversariales, 12 checks), `test_followup.py` (con y sin estudio previo, 5 checks).

**Decisiones de diseño tomadas durante la construcción** (documentadas en el código, resumidas aquí para referencia rápida):
- Parser: extracción híbrida reglas-primero + IA de respaldo. Negaciones ("sin alteraciones", "conservado", etc.) generan Finding con `status="NO_FINDING"` en vez de ser descartadas — preserva trazabilidad de qué fue evaluado.
- El vocabulario de órganos/regiones reconocido por el parser viene del `expected_organs_or_regions` de cada template (parámetro `organ_hints`), no de una lista hardcodeada — así el parser nunca "reconoce" anatomía de un estudio distinto al que se está dictando.
- Normalización singular/plural simple en el parser (`_singularize_simple`) para casos regulares; casos irregulares (ej. "intervertebral"/"intervertebrales") se resuelven listando ambas formas explícitamente en el template JSON correspondiente — nunca se adivina.
- Quality Engine: 3 capas (estructural → coherencia con IA → bloqueo). Nunca corrige automáticamente, solo marca `FLAGGED` con motivo.
- Followup Engine: umbral de cambio real = combinado, ≥3mm absoluto Y ≥20% relativo al tamaño previo (criterio tipo RECIST, decidido con Guille). Detecta transición `NO_FINDING → ACTIVE` como `NEW` real.

🚀 Próximo paso sugerido: conectar el `call_claude` real (usando el mismo patrón que ya funciona en GuardIA/DiagnosIA con `claude-sonnet-4-5`) para activar el fallback de IA del Parser Engine y la Capa 2 del Quality Engine, hoy solo probados con respuestas simuladas. Alternativamente, reemplazar los dictados genéricos de los tests por dictados reales (anonimizados) de Guille para calibrar mejor el vocabulario y los umbrales con casos clínicos reales.
