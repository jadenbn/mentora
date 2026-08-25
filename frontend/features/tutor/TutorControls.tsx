"use client";

import type { TutorMode } from "@/types/tutor";

const MODE_ACTIONS: { mode: TutorMode; label: string }[] = [
  { mode: "mark", label: "Mark" },
  { mode: "hint", label: "Hint" },
  { mode: "explain", label: "Explain" },
  { mode: "stuck", label: "I’m Stuck" },
];

export function TutorControls({
  onAnalyze,
  onClear,
  busyMode,
  disabled = false,
  hasStudentWork = false,
  hasProblem = false,
}: {
  onAnalyze: (mode: TutorMode) => void;
  onClear: () => void;
  busyMode: TutorMode | null;
  disabled?: boolean;
  hasStudentWork?: boolean;
  hasProblem?: boolean;
}) {
  const busy = busyMode !== null;
  const blankCanvas = !hasStudentWork;

  return (
    <div className="grid grid-cols-2 gap-2">
      {MODE_ACTIONS.map(({ mode, label }) => (
        <button
          key={mode}
          className={`min-h-10 rounded-lg border px-3 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-50 disabled:text-slate-400 ${blankCanvas && mode === "stuck" ? "border-blue-600 bg-blue-600 text-white shadow-sm hover:bg-blue-700" : "border-slate-200 bg-white text-slate-900 hover:bg-slate-50"}`}
          disabled={
            disabled ||
            busy ||
            (!hasStudentWork && (mode !== "stuck" || !hasProblem))
          }
          onClick={() => onAnalyze(mode)}
          title={
            !hasStudentWork && (mode !== "stuck" || !hasProblem)
              ? "Draw on the board before using this action."
              : undefined
          }
          type="button"
        >
          {busyMode === mode ? "Thinking…" : label}
        </button>
      ))}

      <button
        className="col-span-2 border-0 px-1 py-1 text-left text-xs font-semibold text-slate-500 underline-offset-2 hover:text-slate-900 hover:underline disabled:cursor-not-allowed disabled:text-slate-300"
        disabled={disabled || busy}
        onClick={onClear}
        type="button"
      >
        Clear feedback
      </button>

    </div>
  );
}
