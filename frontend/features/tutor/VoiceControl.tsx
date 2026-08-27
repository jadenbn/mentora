"use client";

import { useEffect, useState } from "react";
import { Mic, Square, X } from "lucide-react";
import { MAX_RECORDING_MS, type VoiceStatus } from "@/lib/voice/voiceCapture";

/** Every non-idle state says what it is in words, never in colour alone. */
const STATUS_LABEL: Record<VoiceStatus, string> = {
  idle: "",
  requesting: "Waiting for microphone permission…",
  recording: "Recording",
  stopping: "Finishing the recording…",
  transcribing: "Transcribing…",
  // The whiteboard's own thinking indicator already covers the tutor call;
  // repeating it here would put two live regions on one request.
  submitting: "",
};

function formatElapsed(milliseconds: number): string {
  const total = Math.floor(milliseconds / 1_000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/**
 * The microphone, as a student sees it.
 *
 * Presentation only: every transition, timer, and teardown belongs to
 * lib/voice/voiceCapture.ts. Sits in the corner opposite the tutor fan so
 * neither control covers the board or the other.
 */
export function VoiceControl({
  status,
  error,
  startedAt,
  disabled = false,
  disabledReason,
  onStart,
  onStop,
  onCancel,
}: {
  status: VoiceStatus;
  error: string | null;
  startedAt: number | null;
  disabled?: boolean;
  disabledReason?: string;
  onStart: () => void;
  onStop: () => void;
  onCancel: () => void;
}) {
  // The readout starts at 0:00 and is advanced only by the interval, so a
  // stale clock from an earlier recording can never show through.
  const [now, setNow] = useState(0);

  useEffect(() => {
    if (startedAt === null) {
      return;
    }
    const tick = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(tick);
  }, [startedAt]);

  const recording = status === "recording";
  const elapsed = startedAt === null || now <= startedAt ? 0 : now - startedAt;
  const cancellable = status !== "idle" && status !== "submitting";
  const label = STATUS_LABEL[status];

  return (
    <div className="pointer-events-none absolute bottom-4 right-4 z-40 flex flex-col items-end gap-2">
      {error ? (
        <p
          className="max-w-64 rounded-2xl border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-800 shadow-sm"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      {label ? (
        <p
          aria-live="polite"
          className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm"
          role="status"
        >
          {recording ? (
            <span
              aria-hidden="true"
              className="size-2 shrink-0 rounded-full bg-red-600 motion-safe:animate-pulse"
            />
          ) : null}
          {recording ? `${label} ${formatElapsed(elapsed)}` : label}
        </p>
      ) : null}

      <div className="flex items-center gap-2">
        {cancellable ? (
          <button
            aria-label="Cancel recording"
            className="pointer-events-auto flex h-10 items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 shadow-md hover:cursor-grab hover:bg-slate-50 hover:text-slate-900"
            onClick={onCancel}
            type="button"
          >
            <X aria-hidden="true" className="size-3.5" strokeWidth={2.5} />
            Cancel
          </button>
        ) : null}

        {recording ? (
          <button
            aria-label="Stop recording and ask the tutor"
            className="pointer-events-auto flex h-10 items-center gap-1.5 rounded-full border border-blue-600 bg-blue-600 px-4 text-xs font-semibold text-white shadow-md hover:cursor-grab hover:bg-blue-700"
            onClick={onStop}
            type="button"
          >
            <Square aria-hidden="true" className="size-3.5" strokeWidth={3} />
            Stop
          </button>
        ) : status === "idle" || status === "submitting" ? (
          <button
            aria-label="Ask the tutor out loud"
            className="pointer-events-auto flex size-12 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-950 shadow-md hover:cursor-grab hover:bg-slate-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400"
            disabled={disabled || status === "submitting"}
            onClick={onStart}
            title={
              disabled
                ? disabledReason
                : `Hold a question and press Stop. Recordings end after ${MAX_RECORDING_MS / 1_000} seconds.`
            }
            type="button"
          >
            <Mic aria-hidden="true" className="size-5" strokeWidth={2} />
          </button>
        ) : null}
      </div>
    </div>
  );
}
