"use client";

import TemplateSidebar from "@/components/TemplateSidebar";
import DictationForm from "@/components/DictationForm";
import ReportEditor from "@/components/ReportEditor";
import AssistancePanel from "@/components/AssistancePanel";

export default function Home() {
  return (
    <main className="h-screen grid grid-cols-[280px_1fr_320px]">
      {/* Panel 1: template + dictado */}
      <div className="flex flex-col h-full overflow-hidden">
        <div className="flex-1 overflow-hidden">
          <TemplateSidebar />
        </div>
        <DictationForm />
      </div>

      {/* Panel 2: informe */}
      <div className="h-full overflow-hidden border-r border-zinc-800">
        <ReportEditor />
      </div>

      {/* Panel 3: asistencia */}
      <div className="h-full overflow-hidden">
        <AssistancePanel />
      </div>
    </main>
  );
}
