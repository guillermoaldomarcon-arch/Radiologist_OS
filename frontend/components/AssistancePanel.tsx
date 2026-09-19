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
              onClick={() => onAnswer(String(value))}
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
                onAnswer(freeText.trim());
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
    insertPhrasingSuggestion,
  } = useReportStore();

  if (!currentReport) {
    return (
      <div className="h-full flex items-center justify-center text-zinc-500 text-sm p-4 text-center">
        Generá un informe para ver diferenciales, fraseo y el abogado del diablo.
      </div>
    );
  }

  const { devil_questions, differential_panel, phrasing_suggestions } = currentReport;
  const totalItems =
    devil_questions.length + differential_panel.length + phrasing_suggestions.length;

  return (
    <div className="h-full flex flex-col bg-zinc-900 border-l border-zinc-800 overflow-y-auto p-3 space-y-5">
      {totalItems === 0 && (
        <div className="flex-1 flex items-center justify-center text-zinc-600 text-sm">
          Sin observaciones por ahora.
        </div>
      )}

      <Section
        icon={<MessageSquareWarning className="w-3.5 h-3.5 text-red-400" />}
        title="Abogado del diablo"
        count={devil_questions.length}
      >
        {devil_questions.map((q, idx) => (
          <DevilQuestionCard key={idx} question={q} onAnswer={appendDevilAdvocateAnswer} />
        ))}
      </Section>

      <Section
        icon={<HelpCircle className="w-3.5 h-3.5 text-blue-400" />}
        title="Diferenciales"
        count={differential_panel.length}
      >
        {differential_panel.map((diff, idx) => (
          <div key={idx} className="p-3 rounded-md bg-zinc-800/60 border border-zinc-700 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-sm text-zinc-100">{diff.finding_name}</p>
              {diff.validado_por_medico && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400">
                  validado
                </span>
              )}
            </div>
            <ul className="space-y-1">
              {diff.differentials.map((d, i) => (
                <li key={i} className="text-xs">
                  <span className="text-zinc-200 font-medium">{d.name}</span>{" "}
                  <span className="text-zinc-500">({d.likelihood})</span>
                  <p className="text-zinc-500">{d.rationale}</p>
                </li>
              ))}
            </ul>
            <p className="text-[10px] text-zinc-600">{diff.evidence_source}</p>
            {diff.next_question && !diff.resolved && (
              <DevilQuestionCard
                question={{
                  finding_name: diff.finding_name,
                  question: diff.next_question,
                  reason: "Necesario para acotar el diferencial.",
                  rule_type: "DIFF",
                  severity: "advisory",
                  missing_fields: {},
                  closure_candidates: {},
                }}
                onAnswer={appendDevilAdvocateAnswer}
              />
            )}
          </div>
        ))}
      </Section>

      <Section
        icon={<Sparkles className="w-3.5 h-3.5 text-violet-400" />}
        title="Fraseo"
        count={phrasing_suggestions.length}
      >
        {phrasing_suggestions.map((p, idx) => (
          <div key={idx} className="p-3 rounded-md bg-zinc-800/60 border border-zinc-700 space-y-2">
            <p className="text-sm text-zinc-100">{p.finding_name}</p>
            {p.options.map((opt, i) => (
              <div key={i} className="flex items-start gap-2 p-2 rounded bg-zinc-900/60">
                <div className="flex-1">
                  <span className="text-[10px] text-zinc-500 uppercase">{opt.style}</span>
                  <p className="text-xs text-zinc-300">{opt.text}</p>
                </div>
                <button
                  onClick={() => insertPhrasingSuggestion(opt.text)}
                  title="Se agrega al final del informe; reubicala si hace falta"
                  className="shrink-0 flex items-center gap-1 text-[10px] px-2 py-1 rounded bg-violet-600/20 text-violet-300 hover:bg-violet-600/30"
                >
                  <Lightbulb className="w-3 h-3" />
                  Usar
                </button>
              </div>
            ))}
            <p className="text-[10px] text-zinc-600">{p.evidence_source}</p>
          </div>
        ))}
      </Section>
    </div>
  );
}
