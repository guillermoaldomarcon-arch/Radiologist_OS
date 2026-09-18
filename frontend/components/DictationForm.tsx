"use client";

import { useReportStore } from "@/stores/reportStore";
import { Loader2, RotateCcw, Sparkles } from "lucide-react";

export default function DictationForm() {
  const {
    templateId,
    indication,
    dictationText,
    comparativeMode,
    previousDictationText,
    isLoading,
    error,
    currentReport,
    setIndication,
    setDictationText,
    setComparativeMode,
    setPreviousDictationText,
    generateReport,
    reset,
  } = useReportStore();

  return (
    <div className="border-t border-zinc-800 p-3 space-y-2 bg-zinc-900">
      {(currentReport || dictationText.trim()) && (
        <button
          onClick={() => {
            if (window.confirm("¿Limpiar el dictado actual y empezar un informe nuevo?")) {
              reset();
            }
          }}
          className="w-full flex items-center justify-center gap-2 text-xs px-2 py-1.5 rounded-md border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-600"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          Nuevo informe
        </button>
      )}

      <div>
        <label className="text-[11px] text-zinc-500 uppercase tracking-wide">
          Motivo de estudio
        </label>
        <input
          type="text"
          value={indication}
          onChange={(e) => setIndication(e.target.value)}
          className="w-full text-sm mt-1 px-2.5 py-1.5 rounded-md bg-zinc-800 border border-zinc-700 text-zinc-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      </div>

      <div>
        <label className="text-[11px] text-zinc-500 uppercase tracking-wide">Dictado</label>
        <textarea
          value={dictationText}
          onChange={(e) => setDictationText(e.target.value)}
          rows={6}
          className="w-full text-sm mt-1 px-2.5 py-1.5 rounded-md bg-zinc-800 border border-zinc-700 text-zinc-100 resize-y focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      </div>

      <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={comparativeMode}
          onChange={(e) => setComparativeMode(e.target.checked)}
          className="rounded border-zinc-600 bg-zinc-800"
        />
        Es un estudio comparativo
      </label>

      {comparativeMode && (
        <div>
          <label className="text-[11px] text-zinc-500 uppercase tracking-wide">
            Informe previo
          </label>
          <textarea
            value={previousDictationText}
            onChange={(e) => setPreviousDictationText(e.target.value)}
            rows={3}
            className="w-full text-sm mt-1 px-2.5 py-1.5 rounded-md bg-zinc-800 border border-zinc-700 text-zinc-100 resize-y focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
      )}

      {error && <p className="text-xs text-red-400">{error}</p>}

      <button
        onClick={generateReport}
        disabled={isLoading || !templateId || !dictationText.trim()}
        className="w-full flex items-center justify-center gap-2 text-sm px-3 py-2 rounded-md bg-blue-600 text-white hover:bg-blue-500 disabled:bg-zinc-800 disabled:text-zinc-500 disabled:cursor-not-allowed transition-colors"
      >
        {isLoading ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Sparkles className="w-4 h-4" />
        )}
        Generar informe
      </button>
    </div>
  );
}
