"use client";

import { useEffect, useState } from "react";
import { useReportStore } from "@/stores/reportStore";
import { AlertTriangle, Check, Copy, Loader2, ShieldAlert } from "lucide-react";

export default function ReportEditor() {
  const { currentReport, reportDraftText, setReportDraftText, isLoading, error } =
    useReportStore();
  const [copied, setCopied] = useState(false);
  const [showQualityDetail, setShowQualityDetail] = useState(false);

  // El draft ahora vive en el store (ver reportStore.ts) porque Panel 3
  // (Fraseo) necesita poder insertarle texto directamente. Acá solo
  // reseteamos el indicador de "copiado" cuando llega un informe nuevo.
  useEffect(() => {
    if (currentReport) setCopied(false);
  }, [currentReport]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(reportDraftText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center text-zinc-500">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Generando informe...
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center p-6">
        <div className="max-w-sm text-center">
          <AlertTriangle className="w-6 h-6 text-red-400 mx-auto mb-2" />
          <p className="text-sm text-red-400">{error}</p>
        </div>
      </div>
    );
  }

  if (!currentReport) {
    return (
      <div className="h-full flex items-center justify-center text-zinc-500 text-sm">
        Dictá y generá un informe para verlo acá.
      </div>
    );
  }

  const { display_name, unmatched_findings, quality_issues, releasable } = currentReport;
  const hasFlagged = quality_issues.length > 0;

  return (
    <div className="h-full flex flex-col bg-zinc-900">
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
        <h2 className="text-sm font-medium text-zinc-200 truncate">{display_name}</h2>

        <div className="flex items-center gap-2">
          {/* Calidad: sin panel propio -- solo un indicador minimo, interno, si hay algo FLAGGED */}
          {hasFlagged && (
            <div className="relative">
              <button
                onClick={() => setShowQualityDetail((v) => !v)}
                className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-amber-500/10 text-amber-400 hover:bg-amber-500/20"
                title="Controles internos de calidad detectaron algo a revisar"
              >
                <ShieldAlert className="w-3.5 h-3.5" />
                {quality_issues.length}
              </button>
              {showQualityDetail && (
                <div className="absolute right-0 mt-1 w-72 bg-zinc-800 border border-zinc-700 rounded-md shadow-lg p-3 z-10 text-xs text-zinc-300 space-y-2">
                  {quality_issues.map((issue, idx) => (
                    <div key={idx} className="border-b border-zinc-700 last:border-0 pb-2 last:pb-0">
                      <span className="text-zinc-500">
                        {issue.finding_name ?? "General"} · Capa {issue.layer}
                      </span>
                      <p className="text-zinc-200 mt-0.5">{issue.reason}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <span
            className={`flex items-center gap-1 text-xs px-2 py-1 rounded-md ${
              releasable
                ? "bg-emerald-500/10 text-emerald-400"
                : "bg-red-500/10 text-red-400"
            }`}
          >
            {releasable ? <Check className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
            {releasable ? "Listo" : "Con pendientes"}
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <textarea
          value={reportDraftText}
          onChange={(e) => setReportDraftText(e.target.value)}
          className="w-full h-full min-h-[280px] resize-none bg-zinc-800/50 text-zinc-100 text-sm leading-relaxed p-3 rounded-md border border-zinc-700 focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
        />

        {unmatched_findings.length > 0 && (
          <div className="mt-3 p-3 rounded-md bg-amber-500/10 border border-amber-500/20">
            <p className="text-xs font-medium text-amber-400 mb-1">
              Hallazgos dictados sin ubicación en la plantilla:
            </p>
            <ul className="text-xs text-amber-300/90 space-y-0.5 list-disc list-inside">
              {unmatched_findings.map((finding, idx) => (
                <li key={idx}>{finding}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="p-3 border-t border-zinc-800 flex items-center justify-between">
        {!releasable && (
          <span className="text-xs text-red-400">
            Hay hallazgos marcados por revisar antes de considerar esto definitivo.
          </span>
        )}
        <button
          onClick={handleCopy}
          disabled={!releasable}
          title={!releasable ? "Resolvé los pendientes marcados antes de copiar" : undefined}
          className={`ml-auto flex items-center gap-2 text-sm px-3 py-1.5 rounded-md transition-colors ${
            releasable
              ? "bg-blue-600 text-white hover:bg-blue-500"
              : "bg-zinc-800 text-zinc-500 cursor-not-allowed"
          }`}
        >
          <Copy className="w-4 h-4" />
          {copied ? "Copiado" : "Copiar informe"}
        </button>
      </div>
    </div>
  );
}
