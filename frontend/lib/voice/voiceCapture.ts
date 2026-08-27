/**
 * The recording lifecycle, as one explicit state machine.
 *
 * Framework-free on purpose: the microphone, the encoder, and the two network
 * calls all have to be torn down correctly whether the student cancels, the
 * request fails, or the component unmounts mid-flight, and none of that is
 * easier to reason about spread across effects.
 *
 * Voice is an input to the canvas tutor, not a conversation. Nothing is kept:
 * the recording exists as one Blob inside a single run, no object URL is ever
 * created, and the transcript is handed to `submit` and dropped.
 */

import { transcribeSpeech } from "@/lib/api/api";
import {
  startRecording as startBrowserRecording,
  type Recording,
} from "@/lib/voice/microphone";
import { encodeRecordingAsWav } from "@/lib/voice/wav";

/**
 * Long enough for any question a student asks a tutor, short enough that a
 * forgotten recording is not an open microphone.
 */
export const MAX_RECORDING_MS = 60_000;

export type VoiceStatus =
  | "idle"
  | "requesting"
  | "recording"
  | "stopping"
  | "transcribing"
  | "submitting";

export interface VoiceState {
  status: VoiceStatus;
  /** Why the last attempt ended badly. Cleared when the next one starts. */
  error: string | null;
  /** `Date.now()` when recording began, for the elapsed-time readout. */
  startedAt: number | null;
}

export interface VoiceCapture {
  getState(): VoiceState;
  subscribe(listener: () => void): () => void;
  start(): void;
  stop(): void;
  cancel(): void;
  /**
   * Re-point where finished transcripts go.
   *
   * The machine outlives any one render, so the React binding refreshes this
   * rather than rebuilding the machine and stranding a live microphone.
   */
  setSubmit(submit: (transcript: string) => Promise<void>): void;
  /**
   * Arm the machine and return its teardown.
   *
   * Symmetric on purpose. React replays effects in Strict Mode, so a cleanup
   * that permanently retired a machine the component then keeps using would
   * leave the microphone dead in development. Arming here and retiring in the
   * returned function means setup/cleanup/setup ends armed, while a real
   * unmount ends retired with the microphone, timers, and request released.
   */
  mount(): () => void;
}

export interface VoiceCaptureOptions {
  /**
   * Runs the transcript through the tutor. Rejecting here is a tutor failure
   * and is reported as one; succeeding returns the machine to idle, because
   * the canvas itself is the confirmation.
   */
  submit: (transcript: string) => Promise<void>;
  /** Overridden in tests; there is no microphone to record from there. */
  deps?: Partial<VoiceCaptureDeps>;
}

export interface VoiceCaptureDeps {
  startRecording: () => Promise<Recording>;
  encode: (recording: Blob) => Promise<Blob>;
  transcribe: (audio: Blob, signal: AbortSignal) => Promise<string>;
}

/**
 * The recording held no words.
 *
 * The backend refuses a silent recording with its own message, so this is the
 * defence against a transcript that arrives well-formed and empty anyway —
 * provider output is not trusted to honour its schema.
 */
class EmptyTranscriptError extends Error {
  constructor() {
    super("We did not catch that. Try again.");
    this.name = "EmptyTranscriptError";
  }
}

const IDLE: VoiceState = { status: "idle", error: null, startedAt: null };

const BROWSER_DEPS: VoiceCaptureDeps = {
  startRecording: () => startBrowserRecording(),
  encode: encodeRecordingAsWav,
  transcribe: (audio, signal) => transcribeSpeech({ audio, signal }),
};

export function createVoiceCapture(options: VoiceCaptureOptions): VoiceCapture {
  const deps: VoiceCaptureDeps = { ...BROWSER_DEPS, ...options.deps };
  const listeners = new Set<() => void>();

  let state = IDLE;
  let submit = options.submit;
  let retired = false;
  /**
   * Bumped by every start, cancel, and teardown. Async continuations compare
   * against it and return silently when they belong to an abandoned attempt,
   * which is what stops a late transcript from reaching the tutor.
   */
  let run = 0;
  let recording: Recording | null = null;
  let limit: ReturnType<typeof setTimeout> | null = null;
  let inFlight: AbortController | null = null;

  const set = (next: Partial<VoiceState>) => {
    state = { ...state, ...next };
    for (const listener of listeners) {
      listener();
    }
  };

  const clearLimit = () => {
    if (limit !== null) {
      clearTimeout(limit);
      limit = null;
    }
  };

  /** Release everything this attempt owns. Safe from any state. */
  const teardown = () => {
    run += 1;
    clearLimit();
    inFlight?.abort();
    inFlight = null;
    recording?.cancel();
    recording = null;
  };

  const fail = (caught: unknown) => {
    teardown();
    set({ status: "idle", error: messageFor(caught), startedAt: null });
  };

  const start = () => {
    // The only entry point, so this is the whole duplicate-recording guard.
    if (retired || state.status !== "idle") {
      return;
    }
    teardown();
    const attempt = run;
    set({ status: "requesting", error: null, startedAt: null });

    deps.startRecording().then(
      (started) => {
        if (attempt !== run) {
          // Cancelled while the permission prompt was open.
          started.cancel();
          return;
        }
        recording = started;
        set({ status: "recording", startedAt: Date.now() });
        limit = setTimeout(stop, MAX_RECORDING_MS);
      },
      (caught) => {
        if (attempt === run) {
          fail(caught);
        }
      },
    );
  };

  const stop = () => {
    const active = recording;
    if (state.status !== "recording" || !active) {
      return;
    }
    clearLimit();
    const attempt = run;
    const controller = new AbortController();
    inFlight = controller;
    set({ status: "stopping" });

    void (async () => {
      try {
        const audio = await active.stop();
        if (attempt !== run) {
          return;
        }
        recording = null;
        set({ status: "transcribing", startedAt: null });

        const wav = await deps.encode(audio);
        if (attempt !== run) {
          return;
        }
        const transcript = (await deps.transcribe(wav, controller.signal)).trim();
        if (attempt !== run) {
          return;
        }
        if (!transcript) {
          fail(new EmptyTranscriptError());
          return;
        }

        set({ status: "submitting" });
        await submit(transcript);
        if (attempt !== run) {
          return;
        }
        teardown();
        set(IDLE);
      } catch (caught) {
        if (attempt === run) {
          fail(caught);
        }
      }
    })();
  };

  const cancel = () => {
    teardown();
    set(IDLE);
  };

  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    start,
    stop,
    cancel,
    setSubmit: (next) => {
      submit = next;
    },
    mount: () => {
      retired = false;
      return () => {
        retired = true;
        teardown();
        set(IDLE);
      };
    },
  };
}

/**
 * One student-readable sentence per failure.
 *
 * Every error this machine can see already carries a message written for a
 * student — the microphone module's, the API client's status mapping, or the
 * tutor's. The fallback is for the ones that do not exist yet.
 */
function messageFor(caught: unknown): string {
  return caught instanceof Error && caught.message
    ? caught.message
    : "Voice input failed. Try again.";
}
