"use client";

import type { ReactNode } from "react";

/**
 * The one way the tutor says it is busy.
 *
 * Thinking and Transcribing are the same kind of wait — a request the student
 * can only watch — so they read as the same object rather than as two
 * indicators that happen to be near each other. Extracted here because both
 * halves of that wait live in different components: the tutor call belongs to
 * the whiteboard, the transcription to the voice control.
 *
 * Chrome only. Positioning belongs to the caller, which is what lets the same
 * pill sit at the top of the canvas and in the voice stack.
 */
export function StatusPill({
  label,
  animated = true,
  leading,
}: {
  label: string;
  /** The trailing ellipsis that says a request is still running. */
  animated?: boolean;
  /** A state marker that colour alone could not carry, e.g. a recording dot. */
  leading?: ReactNode;
}) {
  return (
    <div
      aria-live="polite"
      className="pointer-events-none flex w-fit items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm"
      role="status"
    >
      {leading}
      <span>
        {label}
        {animated ? (
          <span aria-hidden="true" className="ml-1 inline-flex gap-0.5">
            <span className="animate-bounce [animation-delay:-0.2s] motion-reduce:animate-none">
              .
            </span>
            <span className="animate-bounce [animation-delay:-0.1s] motion-reduce:animate-none">
              .
            </span>
            <span className="animate-bounce motion-reduce:animate-none">.</span>
          </span>
        ) : null}
      </span>
    </div>
  );
}
