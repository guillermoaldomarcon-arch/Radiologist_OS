"use client";

import { useEffect, useState } from "react";
import TemplateSidebar from "@/components/TemplateSidebar";
import DictationForm from "@/components/DictationForm";
import ReportEditor from "@/components/ReportEditor";
import AssistancePanel from "@/components/AssistancePanel";
import { useReportStore } from "@/stores/reportStore";

type MobileTab = "dictado" | "informe" | "asistencia";

const MOBILE_TABS: { id: MobileTab; label: string }[] = [
  { id: "dictado", label: "Dictado" },
  { id: "informe", label: "Informe" },
  { id: "asistencia", label: "Asistencia" },
];

export default function Home() {
  const currentReport = useReportStore((s) => s.currentReport);
  const [activeTab, setActiveTab] = useState<MobileTab>("dictado");

  // Al llegar un informe nuevo (generación inicial o reprocesamiento tras
  // responder al abogado del diablo), saltar directo a la pestaña Informe.
  // Solo tiene efecto en mobile -- en desktop los 3 paneles ya están
  // visibles simultáneamente vía el grid.
  useEffect(() => {
    if (currentReport) setActiveTab("informe");
  }, [currentReport]);

  return (
    <main className="h-screen flex flex-col md:grid md:grid-cols-[280px_1fr_320px]">
      {/* Selector de pestañas -- solo en mobile (<md). En desktop el grid
          de 3 columnas muestra los paneles simultáneamente y esto no se
          renderiza. */}
      <div className="flex md:hidden shrink-0 border-b border-zinc-800 bg-zinc-950">
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

      {/* Panel 1: template + dictado */}
      <div
        className={`${
          activeTab === "dictado" ? "flex" : "hidden"
        } md:flex flex-col flex-1 min-h-0 md:h-full overflow-hidden`}
      >
        <div className="flex-1 overflow-hidden">
          <TemplateSidebar />
        </div>
        <DictationForm />
      </div>

      {/* Panel 2: informe */}
      <div
        className={`${
          activeTab === "informe" ? "block" : "hidden"
        } md:block flex-1 min-h-0 md:h-full overflow-hidden md:border-r md:border-zinc-800`}
      >
        <ReportEditor />
      </div>

      {/* Panel 3: asistencia */}
      <div
        className={`${
          activeTab === "asistencia" ? "block" : "hidden"
        } md:block flex-1 min-h-0 md:h-full overflow-hidden`}
      >
        <AssistancePanel />
      </div>
    </main>
  );
}
