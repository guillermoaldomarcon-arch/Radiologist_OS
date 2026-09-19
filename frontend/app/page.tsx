"use client";

import { useEffect, useState } from "react";
import TemplateSidebar from "@/components/TemplateSidebar";
import DictationForm from "@/components/DictationForm";
import ReportEditor from "@/components/ReportEditor";
import AssistancePanel from "@/components/AssistancePanel";
import { useReportStore, type TemplateSummary } from "@/stores/reportStore";
import { ChevronRight } from "lucide-react";

type MobileTab = "dictado" | "informe" | "asistencia";

const MOBILE_TABS: { id: MobileTab; label: string }[] = [
  { id: "dictado", label: "Dictado" },
  { id: "informe", label: "Informe" },
  { id: "asistencia", label: "Asistencia" },
];

function StudyBar({
  template,
  onOpen,
}: {
  template: TemplateSummary | undefined;
  onOpen: () => void;
}) {
  return (
    <button
      onClick={onOpen}
      className="w-full flex items-center justify-between gap-2 px-3 py-2.5 border-b border-zinc-800 bg-zinc-900 text-left shrink-0"
    >
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-wide text-zinc-500">Estudio</p>
        <p className="text-sm text-zinc-100 truncate">
          {template ? `${template.modality} · ${template.display_name}` : "Elegir estudio..."}
        </p>
      </div>
      <span className="shrink-0 flex items-center gap-1 text-xs px-2.5 py-1 rounded-md bg-blue-600/20 text-blue-300">
        Cambiar
        <ChevronRight className="w-3.5 h-3.5" />
      </span>
    </button>
  );
}

export default function Home() {
  const currentReport = useReportStore((s) => s.currentReport);
  const templateId = useReportStore((s) => s.templateId);
  const templates = useReportStore((s) => s.templates);
  const selectedTemplate = templates.find((t) => t.template_id === templateId);

  const [activeTab, setActiveTab] = useState<MobileTab>("dictado");
  const [showStudyPicker, setShowStudyPicker] = useState(false);

  // Al llegar un informe nuevo (generación inicial o reprocesamiento tras
  // responder al abogado del diablo), saltar directo a la pestaña Informe.
  // Solo tiene efecto en mobile/tablet angosto -- a partir de "wide" los 3
  // paneles ya están visibles simultáneamente vía el grid.
  useEffect(() => {
    if (currentReport) setActiveTab("informe");
  }, [currentReport]);

  // Cerrar el selector de estudio apenas se elige uno.
  useEffect(() => {
    if (templateId) setShowStudyPicker(false);
  }, [templateId]);

  return (
    <main className="h-screen flex flex-col wide:grid wide:grid-cols-[280px_1fr_320px]">
      {/* Selector de pestañas -- por debajo de "wide" (700px). A partir de
          ahí el grid de 3 columnas muestra los paneles simultáneamente y
          esto no se renderiza. */}
      <div className="flex wide:hidden shrink-0 border-b border-zinc-800 bg-zinc-950">
        {MOBILE_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? "border-blue-500 text-zinc-100"
                : "border-transparent text-zinc-500"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Panel 1: estudio + dictado */}
      <div
        className={`${
          activeTab === "dictado" ? "flex" : "hidden"
        } wide:flex flex-col flex-1 min-h-0 wide:h-full overflow-hidden`}
      >
        {/* Por debajo de "wide": barra compacta, la sidebar completa se
            reemplaza por un overlay a pantalla completa para no competir
            por espacio vertical con el formulario de dictado. */}
        <div className="wide:hidden">
          <StudyBar template={selectedTemplate} onOpen={() => setShowStudyPicker(true)} />
        </div>

        {/* A partir de "wide": sidebar completa, siempre visible, como antes. */}
        <div className="hidden wide:flex wide:flex-1 wide:min-h-0 wide:overflow-hidden">
          <TemplateSidebar />
        </div>

        <DictationForm />
      </div>

      {/* Panel 2: informe */}
      <div
        className={`${
          activeTab === "informe" ? "block" : "hidden"
        } wide:block flex-1 min-h-0 wide:h-full overflow-hidden wide:border-r wide:border-zinc-800`}
      >
        <ReportEditor />
      </div>

      {/* Panel 3: asistencia */}
      <div
        className={`${
          activeTab === "asistencia" ? "block" : "hidden"
        } wide:block flex-1 min-h-0 wide:h-full overflow-hidden`}
      >
        <AssistancePanel />
      </div>

      {/* Overlay del selector de estudio -- solo por debajo de "wide". */}
      {showStudyPicker && (
        <div className="wide:hidden fixed inset-0 z-50 bg-zinc-950 flex flex-col">
          <div className="flex items-center justify-between px-3 py-2.5 border-b border-zinc-800 shrink-0">
            <span className="text-sm font-medium text-zinc-200">Elegir estudio</span>
            <button
              onClick={() => setShowStudyPicker(false)}
              className="text-xs px-2.5 py-1 rounded-md text-zinc-400 hover:text-zinc-200"
            >
              Cerrar
            </button>
          </div>
          <div className="flex-1 overflow-hidden">
            <TemplateSidebar />
          </div>
        </div>
      )}
    </main>
  );
}
