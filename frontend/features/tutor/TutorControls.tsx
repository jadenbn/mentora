"use client";

import { useState } from "react";
import { ChevronLeft, Mic, X } from "lucide-react";
import { MAX_RECORDING_MS } from "@/lib/voice/voiceCapture";
import type { TutorMode } from "@/types/tutor";

const MODE_ACTIONS: { mode: TutorMode; label: string }[] = [
  { mode: "mark", label: "Mark" },
  { mode: "hint", label: "Hint" },
  { mode: "explain", label: "Explain" },
  { mode: "stuck", label: "I’m Stuck" },
];

/**
 * The arc, one entry per item that fans out of the chevron: the four tutor
 * modes, then the microphone. Asking out loud is another way to start a tutor
 * request, so it belongs on the same arc rather than in its own corner.
 */
const FAN_POSITIONS = [
  { x: -58, y: -90 },
  { x: -106, y: -46 },
  { x: -120, y: 0 },
  { x: -106, y: 46 },
  { x: -58, y: 90 },
];

const VOICE_INDEX = MODE_ACTIONS.length;

/** Shared by every fanned item so they arrive and leave as one movement. */
function fanStyle(index: number, open: boolean) {
  const position = FAN_POSITIONS[index];
  return {
    transitionDelay: open
      ? `${index * 45}ms`
      : `${(FAN_POSITIONS.length - index) * 30}ms`,
    transitionTimingFunction: "cubic-bezier(0.34, 1.56, 0.64, 1)",
    transform: open
      ? `translate(${position.x}px, ${position.y}px) translate(-50%, -50%) scale(1)`
      : "translate(-50%, -50%) scale(0.72)",
  };
}

export function TutorControls({
  onAnalyze,
  onClear,
  onStartVoice,
  busyMode,
  disabled = false,
  hasStudentWork = false,
  hasProblem = false,
  hasFeedback = false,
}: {
  onAnalyze: (mode: TutorMode) => void;
  onClear: () => void;
  /** Begins a spoken question. The recording itself belongs to VoiceControl. */
  onStartVoice: () => void;
  busyMode: TutorMode | null;
  disabled?: boolean;
  hasStudentWork?: boolean;
  hasProblem?: boolean;
  hasFeedback?: boolean;
}) {
  const busy = busyMode !== null;
  const blankCanvas = !hasStudentWork;
  const [open, setOpen] = useState(false);

  const handleAnalyze = (mode: TutorMode) => {
    setOpen(false);
    onAnalyze(mode);
  };

  // Nothing to look at and nothing to read out: the tutor would have neither
  // the work nor the question. Same gate the canvas-dependent modes use.
  const nothingToTalkAbout = !hasStudentWork && !hasProblem;

  return (
    <div className="pointer-events-none absolute right-6 top-1/2 z-40 h-0 w-0">
      {open ? (
        <button
          aria-label="Close tutor actions"
          className="pointer-events-auto fixed inset-0 z-0 cursor-default"
          onClick={() => setOpen(false)}
          type="button"
        />
      ) : null}

      {MODE_ACTIONS.map(({ mode, label }, index) => {
        const disabledMode =
          disabled ||
          busy ||
          (!hasStudentWork && (mode !== "stuck" || !hasProblem));
        const isPrimary = blankCanvas && mode === "stuck";

        return (
          <button
            key={mode}
            aria-label={label}
            className={`pointer-events-auto absolute left-0 top-0 z-10 flex h-11 min-w-20 items-center justify-center rounded-full border px-3 text-xs font-semibold shadow-md transition-[opacity,transform,background-color,border-color] duration-300 ease-out hover:cursor-grab disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400 ${open ? "opacity-100" : "pointer-events-none opacity-0"} ${isPrimary ? "border-blue-600 bg-blue-600 text-white hover:bg-blue-700" : "border-slate-200 bg-white text-slate-900 hover:bg-slate-50"}`}
            disabled={disabledMode}
            onClick={() => handleAnalyze(mode)}
            style={fanStyle(index, open)}
            title={
              !hasStudentWork && (mode !== "stuck" || !hasProblem)
                ? "Draw on the board before using this action."
                : undefined
            }
            type="button"
          >
            {busyMode === mode ? "Thinking…" : label}
          </button>
        );
      })}

      <button
        aria-label="Ask the tutor out loud"
        className={`pointer-events-auto absolute left-0 top-0 z-10 flex size-11 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-950 shadow-md transition-[opacity,transform,background-color,border-color] duration-300 ease-out hover:cursor-grab hover:bg-slate-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400 ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
        disabled={disabled || busy || nothingToTalkAbout}
        onClick={() => {
          setOpen(false);
          onStartVoice();
        }}
        style={fanStyle(VOICE_INDEX, open)}
        title={
          nothingToTalkAbout
            ? "Draw on the board or add a problem before asking out loud."
            : `Hold a question and press Stop. Recordings end after ${MAX_RECORDING_MS / 1_000} seconds.`
        }
        type="button"
      >
        <Mic aria-hidden="true" className="size-4" strokeWidth={2} />
      </button>

      {hasFeedback ? (
        <button
          aria-label="Clear tutor feedback"
          className={`pointer-events-auto absolute left-0 z-20 flex h-8 min-w-8 items-center justify-center rounded-full border border-slate-200 bg-white px-2 text-[11px] font-semibold text-slate-500 shadow-md transition-[opacity,transform,top] duration-300 ease-out hover:cursor-grab hover:bg-slate-50 hover:text-slate-900 disabled:cursor-not-allowed ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
          disabled={disabled || busy}
          onClick={() => {
            setOpen(false);
            onClear();
          }}
          style={{
            top: 126,
            transitionDelay: open ? `${FAN_POSITIONS.length * 45}ms` : "0ms",
            transitionTimingFunction: "cubic-bezier(0.34, 1.56, 0.64, 1)",
            transform: open
              ? "translate(-50%, -50%) scale(1)"
              : "translate(-50%, -50%) scale(0.72)",
          }}
          type="button"
        >
          Clear
        </button>
      ) : null}

      <button
        aria-expanded={open}
        aria-label={open ? "Close tutor actions" : "Open tutor actions"}
        className={`pointer-events-auto absolute left-0 top-0 z-30 flex h-14 w-12 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-l-full border border-r-0 border-slate-200 bg-white text-slate-950 shadow-md transition-[transform,background-color] duration-200 hover:cursor-grab hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-70 ${open ? "bg-slate-50" : ""}`}
        disabled={disabled || busy}
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        {open ? (
          <X aria-hidden="true" className="size-4 shrink-0" strokeWidth={2.5} />
        ) : (
          <ChevronLeft
            aria-hidden="true"
            className="size-4 shrink-0"
            strokeWidth={2.5}
          />
        )}
      </button>
    </div>
  );
}
