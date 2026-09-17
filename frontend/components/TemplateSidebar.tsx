"use client";

import { useEffect, useMemo, useState } from "react";
import { useReportStore, type TemplateSummary } from "@/stores/reportStore";
import { ChevronRight, ChevronDown, Scan, Search, Loader2 } from "lucide-react";

function normalize(text: string): string {
  // saca acentos para que "torax" encuentre "Tórax"
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function groupByModality(templates: TemplateSummary[]): Map<string, TemplateSummary[]> {
  const groups = new Map<string, TemplateSummary[]>();
  for (const tpl of templates) {
    const key = tpl.modality || "Sin modalidad";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(tpl);
  }
  for (const list of groups.values()) {
    list.sort((a, b) => a.display_name.localeCompare(b.display_name, "es"));
  }
  return groups;
}

function ModalityGroup({
  modality,
  templates,
  defaultExpanded,
}: {
  modality: string;
  templates: TemplateSummary[];
  defaultExpanded: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const { templateId, setTemplateId } = useReportStore();

  return (
    <div>
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-semibold uppercase tracking-wide text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 shrink-0" />
        )}
        <span className="truncate">{modality}</span>
        <span className="ml-auto text-[10px] text-zinc-500 font-normal">{templates.length}</span>
      </button>

      {expanded && (
        <div className="mt-0.5 mb-1">
          {templates.map((tpl) => {
            const isActive = templateId === tpl.template_id;
            return (
              <button
                key={tpl.template_id}
                onClick={() => setTemplateId(tpl.template_id)}
                className={`w-full flex items-center gap-2 pl-8 pr-3 py-1.5 rounded-md text-sm transition-colors
                  ${
                    isActive
                      ? "bg-blue-500/10 text-blue-400 font-medium"
                      : "text-zinc-300 hover:text-zinc-100 hover:bg-zinc-800/50"
                  }`}
              >
                <Scan className="w-4 h-4 shrink-0 text-zinc-500" />
                <span className="truncate">{tpl.display_name}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function TemplateSidebar() {
  const { templates, templatesLoading, error, fetchTemplates, templateId } = useReportStore();
  const [query, setQuery] = useState("");

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  const filtered = useMemo(() => {
    if (!query.trim()) return templates;
    const q = normalize(query);
    return templates.filter((tpl) => normalize(tpl.display_name).includes(q));
  }, [templates, query]);

  const grouped = useMemo(() => groupByModality(filtered), [filtered]);
  const isFiltering = query.trim().length > 0;

  return (
    <div className="h-full flex flex-col bg-zinc-900 border-r border-zinc-800">
      <div className="p-3">
        <div className="relative">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar plantilla..."
            className="w-full text-sm pl-9 pr-3 py-2 rounded-md bg-zinc-800 text-zinc-100 placeholder-zinc-500 border border-zinc-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-4">
        {templatesLoading && (
          <div className="flex items-center gap-2 px-3 py-4 text-sm text-zinc-500">
            <Loader2 className="w-4 h-4 animate-spin" />
            Cargando plantillas...
          </div>
        )}

        {!templatesLoading && error && (
          <div className="mx-2 px-3 py-2 rounded-md bg-red-500/10 text-red-400 text-xs">
            {error}
          </div>
        )}

        {!templatesLoading && !error && templates.length === 0 && (
          <p className="px-3 py-4 text-sm text-zinc-500">No hay plantillas disponibles.</p>
        )}

        {!templatesLoading && !error && templates.length > 0 && grouped.size === 0 && (
          <p className="px-3 py-4 text-sm text-zinc-500">
            Sin resultados para &quot;{query}&quot;.
          </p>
        )}

        {!templatesLoading &&
          !error &&
          Array.from(grouped.entries()).map(([modality, tpls]) => (
            <ModalityGroup
              key={modality}
              modality={modality}
              templates={tpls}
              // con búsqueda activa, todos los grupos abiertos para ver el match de una
              defaultExpanded={isFiltering}
            />
          ))}
      </div>

      {templateId && (
        <div className="p-3 border-t border-zinc-800 text-xs text-zinc-500">
          Plantilla seleccionada:{" "}
          <span className="text-zinc-300 font-medium">{templateId}</span>
        </div>
      )}
    </div>
  );
}
