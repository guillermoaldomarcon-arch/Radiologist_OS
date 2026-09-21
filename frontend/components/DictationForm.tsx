"use client";

import { useRef, useState } from "react";
import { useReportStore } from "@/stores/reportStore";
import { Loader2, Mic, Square, RotateCcw, Sparkles, Undo2 } from "lucide-react";

const MIN_RECORDING_MS = 600;

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
    isTranscribing,
    transcriptionError,
    setIndication,
    setDictationText,
    setComparativeMode,
    setPreviousDictationText,
    generateReport,
    transcribeAudio,
    reset,
  } = useReportStore();

  const [isRecording, setIsRecording] = useState(false);
  const [holdActive, setHoldActive] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const preDictationTextRef = useRef<string>("");
  const recordingStartRef = useRef<number>(0);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      chunksRef.current = [];
      preDictationTextRef.current = dictationText;
      recordingStartRef.current = Date.now();

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());

        const elapsedMs = Date.now() - recordingStartRef.current;
        if (elapsedMs < MIN_RECORDING_MS) {
          return;
        }

        const audioBlob = new Blob(chunksRef.current, { type: "audio/webm" });
        if (audioBlob.size > 0) await transcribeAudio(audioBlob);
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch {
      window.alert("No se pudo acceder al micrófono. Revisá los permisos del navegador.");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current?.state === "inactive") return;
    mediaRecorderRef.current?.stop();
    setIsRecording(false);
  };

  const handleToggleClick = () => {
    if (isTranscribing || holdActive) return;
    if (isRecording) stopRecording();
    else startRecording();
  };

  const handleHoldStart = () => {
    if (isTranscribing || isRecording) return;
    setHoldActive(true);
    startRecording();
  };

  const handleHoldEnd = () => {
    setHoldActive((was) => {
      if (was) stopRecording();
      return false;
    });
  };

  const handleUndoLastDictation = () => {
    setDictationText(preDictationTextRef.current);
  };

  const canUndo = preDictationTextRef.current !== "" && dictationText !== preDictationTextRef.current;

  return (
    <div className="border-t border-zinc-800 p-3 space-y-2 bg-zinc-900">
      {(currentReport || dictationText.trim()) && (
        <button
          onClick={() => {
            if (window.confirm("¿Limpiar el dictado actual y empezar un informe nuevo?")) {
              reset();
            }
          }}
          className="w-full flex items-center justify-center gap-2 text-sm font-medium px-3 py-2 rounded-md bg-amber-600 text-white hover:bg-amber-500 transition-colors"
        >
          <RotateCcw className="w-4 h-4" />
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
        <div className="flex items-center justify-between">
          <label className="text-[11px] text-zinc-500 uppercase tracking-wide">Dictado</label>
          {canUndo && (
            <button
              type="button"
              onClick={handleUndoLastDictation}
              className="flex items-center gap-1 text-xs text-zinc-400 hover:text-zinc-200"
            >
              <Undo2 className="w-3 h-3" />
              Deshacer último dictado
            </button>
          )}
        </div>

        <textarea
          value={dictationText}
          onChange={(e) => setDictationText(e.target.value)}
          rows={6}
          className="w-full text-sm mt-1 px-2.5 py-1.5 rounded-md bg-zinc-800 border border-zinc-700 text-zinc-100 resize-y focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        {transcriptionError && (
          <p className="text-xs text-red-400 mt-1">{transcriptionError}</p>
        )}

        <button
          type="button"
          onClick={handleToggleClick}
          disabled={isTranscribing || holdActive}
          className={`w-full mt-2 flex items-center justify-center gap-2 text-sm font-medium py-4 rounded-lg transition-colors ${
            isRecording && !holdActive
              ? "bg-red-500/20 text-red-400 animate-pulse"
              : isTranscribing
              ? "bg-zinc-800 text-zinc-600 cursor-not-allowed"
              : "bg-blue-500/10 text-blue-400 hover:bg-blue-500/20"
          }`}
        >
          {isRecording && !holdActive ? (
            <Square className="w-4 h-4 fill-current" />
          ) : (
            <Mic className="w-5 h-5" />
          )}
          Manos libres — un toque para grabar, otro para terminar
        </button>

        <button
          type="button"
          onPointerDown={handleHoldStart}
          onPointerUp={handleHoldEnd}
          onPointerCancel={handleHoldEnd}
          onPointerLeave={handleHoldEnd}
          disabled={isTranscribing || (isRecording && !holdActive)}
          style={{ touchAction: "none" }}
          className={`w-full mt-2 flex items-center justify-center gap-2 text-sm font-medium py-4 rounded-lg select-none transition-colors ${
            holdActive
              ? "bg-red-500/20 text-red-400 animate-pulse"
              : isTranscribing
              ? "bg-zinc-800 text-zinc-600 cursor-not-allowed"
              : "bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 active:bg-blue-500/30"
          }`}
        >
          <Mic className="w-5 h-5" />
          Mantener para hablar — soltá para cortar
        </button>
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
        {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
        Generar informe
      </button>
    </div>
  );
}
