"use client";

import { create } from "zustand";

/**
 * Tipos calcados 1:1 de los BaseModel de backend/main.py.
 * Si el contrato del backend cambia, este archivo es lo primero
 * que hay que revisar (y probablemente lo único, ya que todo
 * el resto del frontend consume estos tipos vía el store).
 */

export interface TemplateSummary {
  template_id: string;
  display_name: string;
  modality: string;
}

export interface ReportRequest {
  template_id: string;
  dictation_text: string;
  indication?: string;
  previous_dictation_text?: string;
}

export interface DevilQuestion {
  finding_name: string | null;
  finding_description: string | null;
  question: string;
  reason: string;
  rule_type: string; // "B" | "C" | "E" | "F" (y "G" cuando se agregue)
  severity: string;
  missing_fields: Record<string, unknown>;
  closure_candidates: Record<string, unknown>;
}

export interface DifferentialEntry {
  name: string;
  likelihood: string;
  rationale: string;
}

export interface DifferentialState {
  finding_name: string;
  differentials: DifferentialEntry[];
  next_question: string | null;
  resolved: boolean;
  evidence_source: string;
  validado_por_medico: boolean;
}

export interface PhrasingOption {
  style: string;
  text: string;
}

export interface PhrasingResult {
  finding_name: string;
  diagnosis_key: string;
  options: PhrasingOption[];
  resolved_style: string | null;
  evidence_source: string;
}

export interface QualityIssue {
  finding_name: string | null;
  reason: string;
  layer: number;
}

export interface FollowupResult {
  finding_name: string;
  organ: string | null;
  classification: string; // NEW | STABLE | PROGRESSIVE | RESOLVED | INDETERMINATE
  matched_previous_description: string | null;
}

export interface ReportResponse {
  template_id: string;
  display_name: string;
  report_text: string;
  unmatched_findings: string[];
  devil_questions: DevilQuestion[];
  differential_panel: DifferentialState[];
  phrasing_suggestions: PhrasingResult[];
  quality_issues: QualityIssue[];
  followup: FollowupResult[];
  releasable: boolean;
}

const API_BASE_URL =
  process.env.NEXT_PUBLIC_RADIOLOGIST_OS_API_URL ?? "http://localhost:8000";

interface ReportState {
  // Catálogo
  templates: TemplateSummary[];
  templatesLoading: boolean;

  // Panel 1 — lo que se va a enviar en el próximo POST /report
  templateId: string | null;
  dictationText: string;
  indication: string;
  comparativeMode: boolean; // Panel 1: sección "estudio comparativo" oculta por defecto
  previousDictationText: string;

  // Resultado del último POST /report
  currentReport: ReportResponse | null;

  // Texto editable del informe (Panel 2). Vive en el store, no local a
  // ReportEditor, porque Panel 3 (Fraseo) necesita poder insertar texto
  // ahí directamente -- "fácil de incorporar la sugerencia al informe
  // inmediatamente" no es posible si el estado es privado del componente.
  reportDraftText: string;

  isLoading: boolean;
  error: string | null;

  // Dictado por voz (Panel 1). Separado de isLoading/error (que son del
  // ciclo de POST /report) para que una transcripción fallida no tape la
  // pantalla del informe -- el error se muestra junto al botón de dictar.
  isTranscribing: boolean;
  transcriptionError: string | null;

  // Acciones
  fetchTemplates: () => Promise<void>;
  setTemplateId: (templateId: string) => void;
  setDictationText: (text: string) => void;
  setIndication: (text: string) => void;
  setComparativeMode: (enabled: boolean) => void;
  setPreviousDictationText: (text: string) => void;
  setReportDraftText: (text: string) => void;

  generateReport: () => Promise<void>;

  /**
   * Sube el audio grabado a POST /voice/transcribe (Whisper vía Groq en
   * el backend) y agrega el texto transcripto al dictado existente.
   * El audio nunca se persiste en ningún lado -- se recibe, se
   * transcribe y se descarta, ida y vuelta.
   */
  transcribeAudio: (audioBlob: Blob) => Promise<void>;

  /**
   * Inserta una sugerencia de fraseo al final del borrador editable.
   * Limitación conocida: el backend no devuelve la posición del hallazgo
   * dentro de report_text, así que no se puede insertar "en el lugar
   * correcto" automáticamente -- se agrega al final y el médico la
   * reubica si hace falta. Resolver esto de raíz requeriría que el
   * backend devuelva offsets junto con cada finding.
   */
  insertPhrasingSuggestion: (text: string) => void;

  /**
   * Respuesta del médico a la pregunta de Regla F (nivel de síntesis
   * de la impresión diagnóstica). A diferencia de appendDevilAdvocateAnswer,
   * esto NO toca el dictado ni dispara un nuevo POST /report -- se
   * inserta directamente en el informe (Panel 2), porque no es una
   * corrección de un hallazgo dictado, es una elección editorial sobre
   * cómo presentar la conclusión.
   */
  selectImpressionLevel: (text: string) => void;

  /**
   * Respuesta del médico a una pregunta del abogado del diablo
   * (reglas B/C/E, sin closure_candidates prearmados).
   * Se agrega VISIBLE al final del dictado -- nunca oculto, por
   * trazabilidad médico-legal -- y dispara un nuevo POST /report
   * automáticamente. Como el backend es stateless, el recálculo
   * completo revalida todo, incluyendo errores nuevos que la
   * propia corrección pudiera introducir.
   */
  appendDevilAdvocateAnswer: (answerText: string) => Promise<void>;

  reset: () => void;
}

const initialRequestState = {
  templateId: null as string | null,
  dictationText: "",
  indication: "",
  comparativeMode: false,
  previousDictationText: "",
};

export const useReportStore = create<ReportState>((set, get) => ({
  templates: [],
  templatesLoading: false,

  ...initialRequestState,

  currentReport: null,
  reportDraftText: "",
  isLoading: false,
  error: null,
  isTranscribing: false,
  transcriptionError: null,

  fetchTemplates: async () => {
    if (get().templates.length > 0) return;
    set({ templatesLoading: true, error: null });
    try {
      const res = await fetch(`${API_BASE_URL}/templates`);
      if (!res.ok) throw new Error(`GET /templates -> ${res.status}`);
      const templates: TemplateSummary[] = await res.json();
      set({ templates, templatesLoading: false });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : "Error cargando templates",
        templatesLoading: false,
      });
    }
  },

  setTemplateId: (templateId) => set({ templateId }),
  setDictationText: (dictationText) => set({ dictationText }),
  setIndication: (indication) => set({ indication }),
  setComparativeMode: (comparativeMode) =>
    set({
      comparativeMode,
      // si se desactiva, no mandamos previous_dictation_text aunque haya quedado texto cargado
      previousDictationText: comparativeMode ? get().previousDictationText : "",
    }),
  setPreviousDictationText: (previousDictationText) => set({ previousDictationText }),
  setReportDraftText: (reportDraftText) => set({ reportDraftText }),

  insertPhrasingSuggestion: (text: string) => {
    const current = get().reportDraftText;
    const separator = current.trim().length > 0 ? "\n" : "";
    set({ reportDraftText: `${current}${separator}${text}` });
  },

  selectImpressionLevel: (text: string) => {
    const current = get().reportDraftText;
    const separator = current.trim().length > 0 ? "\n\n" : "";
    set({ reportDraftText: `${current}${separator}IMPRESIÓN DIAGNÓSTICA:\n${text}` });
  },

  generateReport: async () => {
    const { templateId, dictationText, indication, comparativeMode, previousDictationText } =
      get();

    if (!templateId) {
      set({ error: "Falta seleccionar un template." });
      return;
    }
    if (!dictationText.trim()) {
      set({ error: "El dictado no puede estar vacío." });
      return;
    }

    set({ isLoading: true, error: null });

    const payload: ReportRequest = {
      template_id: templateId,
      dictation_text: dictationText,
      indication: indication.trim() || undefined,
      previous_dictation_text:
        comparativeMode && previousDictationText.trim()
          ? previousDictationText
          : undefined,
    };

    try {
      const res = await fetch(`${API_BASE_URL}/report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        // 404 template inexistente, 400 dictado vacío, 502 error de Claude
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail ?? `POST /report -> ${res.status}`);
      }

      const report: ReportResponse = await res.json();
      // El draft se resincroniza con cada informe nuevo del backend --
      // cualquier edición manual previa del médico sobre el texto anterior
      // se pierde, es el mismo trade-off que ya asumimos con el reprocesamiento
      // completo al responder al abogado del diablo.
      set({ currentReport: report, reportDraftText: report.report_text, isLoading: false });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : "Error generando el informe",
        isLoading: false,
      });
    }
  },

  appendDevilAdvocateAnswer: async (answerText: string) => {
    const trimmed = answerText.trim();
    if (!trimmed) return;

    const currentDictation = get().dictationText;
    const updatedDictation = `${currentDictation}\n${trimmed}`;

    set({ dictationText: updatedDictation });
    await get().generateReport();
  },

  transcribeAudio: async (audioBlob: Blob) => {
    set({ isTranscribing: true, transcriptionError: null });

    const formData = new FormData();
    formData.append("file", audioBlob, "dictado.webm");

    try {
      const res = await fetch(`${API_BASE_URL}/voice/transcribe`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail ?? `POST /voice/transcribe -> ${res.status}`);
      }

      const data: { text: string } = await res.json();
      const transcribed = data.text.trim();

      if (transcribed) {
        const current = get().dictationText;
        set({ dictationText: current ? `${current} ${transcribed}` : transcribed });
      }
      set({ isTranscribing: false });
    } catch (err) {
      set({
        transcriptionError: err instanceof Error ? err.message : "Error transcribiendo el audio",
        isTranscribing: false,
      });
    }
  },

  reset: () =>
    set({
      templateId: get().templateId,
      dictationText: "",
      indication: "",
      comparativeMode: false,
      previousDictationText: "",
      currentReport: null,
      reportDraftText: "",
      error: null,
      transcriptionError: null,
    }),
}));
