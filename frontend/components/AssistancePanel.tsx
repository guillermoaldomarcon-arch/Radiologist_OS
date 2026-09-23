"use client";

import { useState } from "react";
import { useReportStore } from "@/stores/reportStore";
import { HelpCircle, Lightbulb, MessageSquareWarning, Sparkles } from "lucide-react";

function DevilQuestionCard({
  question,
  onAnswer,
}: {
  question: import("@/stores/reportStore").DevilQuestion;
  onAnswer: (text: string) => void;
}) {
  const [freeText, setFreeText] = useState("");
  const candidateEntries = Object.entries(question.closure_candidates ?? {}).filter(
    ([, value]) => value !== null && value !== undefined && String(value).trim() !== ""
  );

  const answerWithContext = (value: string) => {
    const context = question.finding_name ? `${question.finding_name}: ` : "";
    onAnswer(`${context}${value}`);
  };

  const missingFieldNames = Object.keys(question.missing_fields ?? {});
  const hasCandidates = candidateEntries.length > 0;

  return (
    <div className="p-3 rounded-md bg-zinc-800/60 border border-zinc-700 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-zinc-100">{question.question}</p>
        <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-zinc-700 text-zinc-400">
          Regla {question.rule_type}
        </span>
      </div>

      {question.finding_name && (
        <p className="text-xs text-zinc-500">Sobre: {question.finding_name}</p>
      )}
      <p className="text-xs text-zinc-500">{question.reason}</p>

      {missingFieldNames.length > 0 && (
        <p className="text-xs text-amber-400">Faltan: {missingFieldNames.join(", ")}</p>
      )}

      {hasCandidates ? (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {candidateEntries.map(([key, value]) => (
            <button
              key={key}
              onClick={() => answerWithContext(String(value))}
              className="text-xs px-2 py-1 rounded-md bg-blue-600/20 text-blue-300 hover:bg-blue-600/30"
            >
              {String(value)}
            </button>
          ))}
        </div>
      ) : (
        <div className="flex gap-1.5 pt-1">
          <input
            type="text"
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            placeholder="Respuesta..."
            className="flex-1 text-xs px-2 py-1.5 rounded-md bg-zinc-900 border border-zinc-700 text-zinc-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <button
            onClick={() => {
              if (freeText.trim()) {
                answerWithContext(freeText.trim());
                setFreeText("");
              }
            }}
            className="text-xs px-2.5 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-500 shrink-0"
          >
            Agregar
          </button>
        </div>
      )}
    </div>
  );
}

function Section({
  icon,
  title,
  count,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  if (count === 0) return null;
  return (
    <div>
      <div className="flex items-center gap-2 px-1 mb-2">
        {icon}
        <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400">{title}</p>
        <span className="text-[10px] text-zinc-600">{count}</span>
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

export default function AssistancePanel() {
  const {
    currentReport,
    appendDevilAdvocateAnswer,
