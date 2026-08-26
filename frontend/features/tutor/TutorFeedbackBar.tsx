"use client";

import { ChevronLeft, ChevronRight, Eye, EyeOff } from "lucide-react";
import { ProblemBody } from "@/features/problems/ProblemCard";
import type { FeedbackLayer } from "@/lib/tutor/feedbackHistory";

export function TutorFeedbackBar({
  busy,
  error,
  layer,
  activeIndex,
  layerCount,
  visible,
  warning,
  onPrevious,
  onNext,
  onToggle,
}: {
  busy: boolean;
  error: string | null;
  layer: FeedbackLayer | null;
  activeIndex: number;
  layerCount: number;
  visible: boolean;
  warning: string | null;
  onPrevious: () => void;
  onNext: () => void;
  onToggle: () => void;
}) {
  if (!layer && !warning && !error) return null;

  const hasLayer = layer !== null;
  const atStart = activeIndex <= 0;
  const atEnd = activeIndex < 0 || activeIndex >= layerCount - 1;

  return (
    <div className="pointer-events-none mx-auto flex w-full max-w-6xl min-w-0 flex-col items-center gap-1 text-sm">
      {error ? (
        <span aria-live="assertive" className="text-xs font-semibold text-red-700" role="alert">
          {error}
        </span>
      ) : warning ? (
        <span className="text-xs font-semibold text-amber-700" role="status">
          {warning}
        </span>
      ) : null}

      {hasLayer ? (
        <>
          <div className="pointer-events-auto flex items-center justify-center gap-2">
            <button
              aria-label="Previous tutor feedback"
              className="flex size-7 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white/80 p-1 text-slate-500 shadow-sm hover:cursor-grab hover:bg-white hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-35"
              disabled={busy || atStart}
              onClick={onPrevious}
              title="Previous feedback"
              type="button"
            >
              <ChevronLeft aria-hidden="true" className="size-4" />
            </button>
            <span className="shrink-0 text-xs tabular-nums text-slate-400">
              {activeIndex + 1} / {layerCount}
            </span>
            <button
              aria-label="Next tutor feedback"
              className="flex size-7 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white/80 p-1 text-slate-500 shadow-sm hover:cursor-grab hover:bg-white hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-35"
              disabled={busy || atEnd}
              onClick={onNext}
              title="Next feedback"
              type="button"
            >
              <ChevronRight aria-hidden="true" className="size-4" />
            </button>
            <button
              aria-label={visible ? "Hide tutor feedback" : "Show tutor feedback"}
              aria-pressed={visible}
              className="flex size-7 shrink-0 items-center justify-center rounded-full p-1 text-slate-500 hover:cursor-grab hover:bg-slate-100 hover:text-slate-900"
              onClick={onToggle}
              title={visible ? "Hide feedback" : "Show feedback"}
              type="button"
            >
              {visible ? (
                <Eye aria-hidden="true" className="size-4" />
              ) : (
                <EyeOff aria-hidden="true" className="size-4" />
              )}
            </button>
          </div>
          <div
            className={`pointer-events-auto min-w-0 max-w-full overflow-hidden text-center ${visible ? "text-slate-950" : "text-slate-400"}`}
            title={visible ? layer.response.summary : "Feedback hidden"}
          >
            <ProblemBody
              className="problem-katex feedback-katex max-w-full whitespace-pre-wrap text-[clamp(1rem,1.5vw,1.25rem)] leading-relaxed text-inherit"
              prompt={visible ? layer.response.summary : "Feedback hidden"}
            />
          </div>
        </>
      ) : null}
    </div>
  );
}
