"use client";

import type { TutorMode } from "@/types/tutor";

const MODE_ACTIONS: { mode: TutorMode; label: string }[] = [
  { mode: "mark", label: "Mark" },
  { mode: "hint", label: "Hint" },
  { mode: "explain", label: "Explain" },
  { mode: "stuck", label: "I’m Stuck" },
];

// Not built yet: Select for AI needs a selection crop, Import problem needs the
// problem-import pipeline.
const PENDING_ACTIONS = ["Select for AI", "Import problem"];

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

  return (
    <div className="flex flex-wrap gap-2">
      {MODE_ACTIONS.map(({ mode, label }) => (
        <button
          key={mode}
          className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm font-semibold text-slate-900 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
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
        className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm font-semibold text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
        disabled={disabled || busy}
        onClick={onClear}
        type="button"
      >
        Clear feedback
      </button>

      {PENDING_ACTIONS.map((action) => (
        <button
          key={action}
          className="rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm font-semibold text-slate-400"
          disabled
          type="button"
        >
          {action}
        </button>
      ))}
    </div>
  );
}
