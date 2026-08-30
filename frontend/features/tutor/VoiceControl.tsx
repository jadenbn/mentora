"use client";

import { useEffect, useRef, useState } from "react";
import { RotateCcw, Send, Square, X } from "lucide-react";
import { StatusPill } from "@/features/tutor/StatusPill";
import type { VoicePhase } from "@/lib/voice/voiceCapture";
import { MAX_TRANSCRIPT_CHARS } from "@/types/voice";

/** Every waiting state says what it is in words, never in colour alone. */
const STATUS_LABEL: Partial<Record<VoicePhase["status"], string>> = {
  requesting: "Waiting for microphone permission",
  recording: "Recording",
  stopping: "Finishing the recording",
  transcribing: "Transcribing",
};

function formatElapsed(milliseconds: number): string {
  const total = Math.floor(milliseconds / 1_000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/**
 * A spoken question, from the moment recording starts to the moment it is sent.
 *
 * Presentation only: every transition, timer, and teardown belongs to
 * lib/voice/voiceCapture.ts. The microphone that begins all this lives with
 * the other tutor actions in TutorControls — this surface exists only while a
 * question is in progress, so a quiet board stays a quiet board.
 *
 * The transcript is shown and editable before anything is sent. Speech
 * recognition is wrong often enough that spending a tutor call on a misheard
 * question is worse than one extra tap.
 */
export function VoiceControl({
  phase,
  error,
  onStop,
  onCancel,
  onEdit,
  onAsk,
  onRerecord,
}: {
  phase: VoicePhase;
  error: string | null;
  onStop: () => void;
  onCancel: () => void;
  onEdit: (transcript: string) => void;
  onAsk: () => void;
  onRerecord: () => void;
}) {
  // The readout starts at 0:00 and is advanced only by the interval, so a
  // stale clock from an earlier recording can never show through.
  const [now, setNow] = useState(0);
  const editor = useRef<HTMLTextAreaElement | null>(null);
  const startedAt = phase.status === "recording" ? phase.startedAt : null;
  const confirming = phase.status === "confirming";

  useEffect(() => {
    if (startedAt === null) {
      return;
    }
    const tick = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(tick);
  }, [startedAt]);

  // Review is a new place to be, so take the student there rather than leaving
  // focus on a microphone button that is no longer on screen.
  useEffect(() => {
    if (confirming) {
      editor.current?.focus();
    }
  }, [confirming]);

  if (phase.status === "idle" && !error) {
    return null;
  }

  const elapsed = startedAt === null || now <= startedAt ? 0 : now - startedAt;
  const label = STATUS_LABEL[phase.status];
  const cancellable = phase.status !== "idle" && phase.status !== "submitting";
  const question =
    phase.status === "confirming" || phase.status === "submitting"
      ? phase.transcript
      : null;

  return (
    <div className="pointer-events-none absolute bottom-4 right-4 z-40 flex w-80 max-w-[calc(100vw-2rem)] flex-col items-end gap-2">
      {error ? (
        <p
          className="rounded-2xl border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-800 shadow-sm"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      {label ? (
        <StatusPill
          animated={phase.status !== "recording"}
          label={
            phase.status === "recording" ? `${label} ${formatElapsed(elapsed)}` : label
          }
          leading={
            phase.status === "recording" ? (
              <span
                aria-hidden="true"
                className="size-2 shrink-0 rounded-full bg-red-600 motion-safe:animate-pulse"
              />
            ) : null
          }
        />
      ) : null}

      {question !== null ? (
        <div className="pointer-events-auto w-full rounded-2xl border border-slate-200 bg-white p-3 shadow-md">
          <label
            className="block text-xs font-semibold text-slate-500"
            htmlFor="voice-transcript"
          >
            You asked
          </label>
          <textarea
            className="mt-1.5 block w-full resize-none rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-950 disabled:bg-slate-50 disabled:text-slate-500"
            disabled={!confirming}
            id="voice-transcript"
            maxLength={MAX_TRANSCRIPT_CHARS}
            onChange={(event) => onEdit(event.target.value)}
            ref={editor}
            rows={3}
            value={question}
          />
          <p className="mt-1 text-[11px] text-slate-500">
            Edit anything the tutor misheard, then ask.
          </p>
        </div>
      ) : null}

      <div className="flex items-center gap-2">
        {cancellable ? (
          <button
            aria-label={confirming ? "Discard this question" : "Cancel recording"}
            className="pointer-events-auto flex h-10 items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 shadow-md hover:cursor-grab hover:bg-slate-50 hover:text-slate-900"
            onClick={onCancel}
            type="button"
          >
            <X aria-hidden="true" className="size-3.5" strokeWidth={2.5} />
            Cancel
          </button>
        ) : null}

        {confirming ? (
          <>
            <button
              aria-label="Record the question again"
              className="pointer-events-auto flex h-10 items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 shadow-md hover:cursor-grab hover:bg-slate-50 hover:text-slate-900"
              onClick={onRerecord}
              type="button"
            >
              <RotateCcw aria-hidden="true" className="size-3.5" strokeWidth={2.5} />
              Rerecord
            </button>
            <button
              aria-label="Ask the tutor this question"
              className="pointer-events-auto flex h-10 items-center gap-1.5 rounded-full border border-blue-600 bg-blue-600 px-4 text-xs font-semibold text-white shadow-md hover:cursor-grab hover:bg-blue-700"
              onClick={onAsk}
              type="button"
            >
              <Send aria-hidden="true" className="size-3.5" strokeWidth={2.5} />
              Ask
            </button>
          </>
        ) : null}

        {phase.status === "recording" ? (
          <button
            aria-label="Stop recording"
            className="pointer-events-auto flex h-10 items-center gap-1.5 rounded-full border border-blue-600 bg-blue-600 px-4 text-xs font-semibold text-white shadow-md hover:cursor-grab hover:bg-blue-700"
            onClick={onStop}
            type="button"
          >
            <Square aria-hidden="true" className="size-3.5" strokeWidth={3} />
            Stop
          </button>
        ) : null}
      </div>
    </div>
  );
}
