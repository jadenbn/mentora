"use client";

import {
  BookOpenText,
  CircleCheckBig,
  LifeBuoy,
  Lightbulb,
  Trash2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { TutorMode } from "@/types/tutor";

const MODE_ACTIONS: {
  mode: TutorMode;
  label: string;
  description: string;
  icon: LucideIcon;
  tone: string;
}[] = [
  {
    mode: "mark",
    label: "Mark",
    description: "Check the work visible now",
    icon: CircleCheckBig,
    tone: "border-[#bfd2c5] bg-[#f1f7f2] text-[#315843] hover:bg-[#e8f2ea]",
  },
  {
    mode: "hint",
    label: "Hint",
    description: "Give one useful next nudge",
    icon: Lightbulb,
    tone: "border-[#e4cf9f] bg-[#fff9eb] text-[#75591e] hover:bg-[#fbf1d8]",
  },
  {
    mode: "explain",
    label: "Explain",
    description: "Clarify this step or mistake",
    icon: BookOpenText,
    tone: "border-[#cbd3dd] bg-[#f5f7fa] text-[#40566f] hover:bg-[#eaf0f6]",
  },
  {
    mode: "stuck",
    label: "I’m Stuck",
    description: "Scaffold the next meaningful step",
    icon: LifeBuoy,
    tone: "border-[#d7c7c1] bg-[#fbf4f1] text-[#714b40] hover:bg-[#f5e9e4]",
  },
];

export function TutorControls({
  onAnalyze,
  onClear,
  busyMode,
  disabled = false,
}: {
  onAnalyze: (mode: TutorMode) => void;
  onClear: () => void;
  busyMode: TutorMode | null;
  disabled?: boolean;
}) {
  const busy = busyMode !== null;

  return (
    <div>
      <div className="grid grid-cols-2 gap-2">
        {MODE_ACTIONS.map(({ mode, label, description, icon: Icon, tone }) => (
          <button
            key={mode}
            className={`min-h-24 rounded-xl border p-3 text-left transition disabled:cursor-not-allowed disabled:opacity-45 ${tone}`}
            disabled={disabled || busy}
            onClick={() => onAnalyze(mode)}
            type="button"
          >
            <Icon aria-hidden="true" className="mb-3 size-5" strokeWidth={2.2} />
            <span className="block text-sm font-bold">
              {busyMode === mode ? "Thinking…" : label}
            </span>
            <span className="mt-0.5 block text-[0.7rem] leading-snug opacity-75">
              {description}
            </span>
          </button>
        ))}
      </div>

      <button
        className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-[#d9d6cc] bg-white px-3 py-2 text-sm font-semibold text-[#536057] hover:bg-[#f6f5f1] disabled:cursor-not-allowed disabled:text-slate-400"
        disabled={disabled || busy}
        onClick={onClear}
        type="button"
      >
        <Trash2 aria-hidden="true" className="size-4" />
        Clear feedback
      </button>

    </div>
  );
}
