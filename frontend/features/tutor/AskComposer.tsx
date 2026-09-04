"use client";

import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type SyntheticEvent,
} from "react";
import { Mic, RotateCcw, Send, Square, X } from "lucide-react";
import { useMaybeEditor } from "tldraw";
import { StatusPill } from "@/features/tutor/StatusPill";
import {
  MAX_RECORDING_MS,
  type VoicePhase,
} from "@/lib/voice/voiceCapture";
import { MAX_TRANSCRIPT_CHARS } from "@/types/voice";

const STATUS_LABEL: Partial<Record<VoicePhase["status"], string>> = {
  requesting: "Starting microphone",
  recording: "Recording",
  stopping: "Finishing the recording",
  transcribing: "Transcribing",
};

function formatElapsed(milliseconds: number): string {
  const total = Math.floor(milliseconds / 1_000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function errorMessage(caught: unknown): string {
  return caught instanceof Error && caught.message
    ? caught.message
    : "The tutor request failed.";
}

/** One compact text surface for typed questions and reviewed voice transcripts. */
export function AskComposer({
  open,
  hasSelection,
  hasStudentWork,
  phase,
  voiceError,
  onAsk,
  onClose,
  onVoiceAsk,
  onVoiceCancel,
  onVoiceEdit,
  onVoiceRerecord,
  onVoiceStart,
  onVoiceStop,
}: {
  open: boolean;
  hasSelection: boolean;
  hasStudentWork: boolean;
  phase: VoicePhase;
  voiceError: string | null;
  onAsk: (question: string) => Promise<void>;
  onClose: () => void;
  onVoiceAsk: () => void;
  onVoiceCancel: () => void;
  onVoiceEdit: (transcript: string) => void;
  onVoiceRerecord: () => void;
  onVoiceStart: () => void;
  onVoiceStop: () => void;
}) {
  const editor = useMaybeEditor();
  const textarea = useRef<HTMLTextAreaElement | null>(null);
  const [draft, setDraft] = useState("");
  const [typedError, setTypedError] = useState<string | null>(null);
  const [submittingText, setSubmittingText] = useState(false);
  const [now, setNow] = useState(0);

  const startedAt = phase.status === "recording" ? phase.startedAt : null;
  const reviewingVoice =
    phase.status === "confirming" || phase.status === "submitting";
  const question = reviewingVoice ? phase.transcript : draft;
  const inputEnabled =
    !submittingText &&
    (phase.status === "idle" || phase.status === "confirming");
  const canSend = inputEnabled && question.trim().length > 0;
  const waitingLabel = STATUS_LABEL[phase.status];
  const displayedError = typedError ?? voiceError;

  useEffect(() => {
    if (startedAt === null) return;
    const tick = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(tick);
  }, [startedAt]);

  useEffect(() => {
    if (open && inputEnabled) {
      textarea.current?.focus();
    }
  }, [inputEnabled, open, phase.status]);

  if (!open) return null;

  const markAsHandled = (event: SyntheticEvent) => {
    editor?.markEventAsHandled(event);
  };

  const close = () => {
    if (submittingText || phase.status === "submitting") return;
    setDraft("");
    setTypedError(null);
    onClose();
  };

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!inputEnabled) return;

    if (phase.status === "confirming") {
      onVoiceAsk();
      return;
    }

    const studentQuestion = draft.trim();
    if (!studentQuestion) {
      setTypedError("There is nothing to ask yet.");
      return;
    }
    if (studentQuestion.length > MAX_TRANSCRIPT_CHARS) {
      setTypedError(
        `Questions are limited to ${MAX_TRANSCRIPT_CHARS} characters.`,
      );
      return;
    }

    onVoiceCancel();
    setTypedError(null);
    setSubmittingText(true);
    try {
      await onAsk(studentQuestion);
      setDraft("");
      setSubmittingText(false);
      onClose();
    } catch (caught) {
      setTypedError(errorMessage(caught));
      setSubmittingText(false);
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    editor?.markEventAsHandled(event);
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      void submit();
    }
  };

  const contextLabel = hasSelection
    ? "Using selection"
    : hasStudentWork
      ? "Using all work"
      : "Using problem only";
  const prompt = hasSelection
    ? "Ask about your selection"
    : hasStudentWork
      ? "Ask about your work"
      : "Ask about the problem";
  const elapsed = startedAt === null || now <= startedAt ? 0 : now - startedAt;

  return (
    <form
      aria-label="Ask AI"
      className="pointer-events-auto absolute right-20 top-1/2 z-50 w-80 max-w-[calc(100vw-7rem)] -translate-y-1/2 rounded-2xl border border-slate-200 bg-white p-3 shadow-xl"
      onKeyDown={markAsHandled}
      onPointerDown={markAsHandled}
      onPointerUp={markAsHandled}
      onSubmit={(event) => void submit(event)}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-950">Ask AI</p>
          <p className="mt-0.5 text-xs text-slate-500">{contextLabel}</p>
        </div>
        <button
          aria-label="Close Ask AI"
          className="flex size-8 shrink-0 items-center justify-center rounded-full text-slate-500 hover:cursor-grab hover:bg-slate-100 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={submittingText || phase.status === "submitting"}
          onClick={close}
          type="button"
        >
          <X aria-hidden="true" className="size-4" strokeWidth={2.5} />
        </button>
      </div>

      <label className="sr-only" htmlFor="ask-ai-question">
        {prompt}
      </label>
      <textarea
        aria-label={prompt}
        className="mt-3 block w-full resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-950 outline-none placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50 disabled:text-slate-500"
        disabled={!inputEnabled}
        id="ask-ai-question"
        maxLength={MAX_TRANSCRIPT_CHARS}
        onChange={(event) => {
          setTypedError(null);
          if (phase.status === "confirming") {
            onVoiceEdit(event.target.value);
          } else {
            if (voiceError) onVoiceCancel();
            setDraft(event.target.value);
          }
        }}
        onKeyDown={handleKeyDown}
        placeholder={prompt}
        ref={textarea}
        rows={4}
        value={question}
      />

      {displayedError ? (
        <p className="mt-2 text-xs font-medium text-red-700" role="alert">
          {displayedError}
        </p>
      ) : null}

      {waitingLabel ? (
        <div className="mt-2 flex justify-center">
          <StatusPill
            animated={phase.status !== "recording"}
            label={
              phase.status === "recording"
                ? `${waitingLabel} ${formatElapsed(elapsed)}`
                : waitingLabel
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
        </div>
      ) : null}

      <div className="mt-3 flex items-center justify-between gap-2">
        {phase.status === "recording" ? (
          <button
            aria-label="Stop recording"
            className="flex h-10 items-center gap-1.5 rounded-full border border-red-200 bg-red-50 px-3 text-xs font-semibold text-red-700 hover:cursor-grab hover:bg-red-100"
            onClick={onVoiceStop}
            type="button"
          >
            <Square aria-hidden="true" className="size-3.5" strokeWidth={3} />
            Stop
          </button>
        ) : phase.status === "idle" ? (
          <button
            aria-label="Ask with microphone"
            className="flex h-10 items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 hover:cursor-grab hover:bg-slate-50 hover:text-slate-900"
            onClick={() => {
              setTypedError(null);
              onVoiceStart();
            }}
            title={`Record for up to ${MAX_RECORDING_MS / 1_000} seconds.`}
            type="button"
          >
            <Mic aria-hidden="true" className="size-3.5" strokeWidth={2.5} />
            Microphone
          </button>
        ) : phase.status === "confirming" ? (
          <button
            aria-label="Record the question again"
            className="flex h-10 items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 hover:cursor-grab hover:bg-slate-50 hover:text-slate-900"
            onClick={onVoiceRerecord}
            type="button"
          >
            <RotateCcw aria-hidden="true" className="size-3.5" strokeWidth={2.5} />
            Rerecord
          </button>
        ) : (
          <span />
        )}

        <button
          aria-label="Ask the tutor this question"
          className="flex h-10 items-center gap-1.5 rounded-full border border-blue-600 bg-blue-600 px-4 text-xs font-semibold text-white hover:cursor-grab hover:bg-blue-700 disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400"
          disabled={!canSend}
          type="submit"
        >
          <Send aria-hidden="true" className="size-3.5" strokeWidth={2.5} />
          {submittingText || phase.status === "submitting" ? "Asking…" : "Send"}
        </button>
      </div>
    </form>
  );
}
