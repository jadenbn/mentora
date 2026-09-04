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
 *
 * Transcribing does not ask the tutor anything. The words go to a confirmation
 * step first, where the student can correct what the model heard, because
 * speech recognition is wrong often enough that spending a tutor call on a
 * misheard question is worse than one extra tap.
 */

import { transcribeSpeech } from "@/lib/api/api";
import {
  startRecording as startBrowserRecording,
  type Recording,
} from "@/lib/voice/microphone";
import { encodeRecordingAsWav } from "@/lib/voice/wav";
import { MAX_TRANSCRIPT_CHARS } from "@/types/voice";

/**
 * Long enough for any question a student asks a tutor, short enough that a
 * forgotten recording is not an open microphone.
 */
export const MAX_RECORDING_MS = 60_000;

/**
 * What the machine is doing, and the data that step owns.
 *
 * A union rather than a widening bag of optional fields: a transcript exists
 * exactly while there is one to review or send, and an elapsed clock exists
 * exactly while the microphone is open. Neither can be read from a step that
 * does not have one.
 */
export type VoicePhase =
  | { status: "idle" }
  | { status: "requesting" }
  | { status: "recording"; startedAt: number }
  | { status: "stopping" }
  | { status: "transcribing" }
  | { status: "confirming"; transcript: string }
  | { status: "submitting"; transcript: string };

export interface VoiceState {
  phase: VoicePhase;
  /**
   * Why the last attempt ended badly. Orthogonal to the phase: it outlives the
   * step that produced it so the student can still read it, and is cleared
   * when the next attempt starts.
   */
  error: string | null;
}

export interface VoiceCapture {
  getState(): VoiceState;
  subscribe(listener: () => void): () => void;
  start(): void;
  stop(): void;
  cancel(): void;
  /** Correct what the model heard. Only meaningful while confirming. */
  edit(transcript: string): void;
  /** Send the reviewed transcript to the tutor. The only path that does. */
  ask(): void;
  /** Throw the transcript away and record the question again. */
  rerecord(): void;
  /**
   * Re-point where confirmed transcripts go.
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
   * Runs the confirmed transcript through the tutor. Rejecting here is a tutor
   * failure and is reported as one, leaving the question under review so it
   * can be sent again; succeeding returns the machine to idle, because the
   * canvas itself is the confirmation.
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

const IDLE: VoiceState = { phase: { status: "idle" }, error: null };

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

  const set = (next: VoiceState) => {
    state = next;
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
    set({ phase: { status: "idle" }, error: messageFor(caught) });
  };

  const start = () => {
    // The only entry point, so this is the whole duplicate-recording guard.
    if (retired || state.phase.status !== "idle") {
      return;
    }
    teardown();
    const attempt = run;
    set({ phase: { status: "requesting" }, error: null });

    deps.startRecording().then(
      (started) => {
        if (attempt !== run) {
          // Cancelled while the permission prompt was open.
          started.cancel();
          return;
        }
        recording = started;
        set({ phase: { status: "recording", startedAt: Date.now() }, error: null });
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
    if (state.phase.status !== "recording" || !active) {
      return;
    }
    clearLimit();
    const attempt = run;
    const controller = new AbortController();
    inFlight = controller;
    set({ phase: { status: "stopping" }, error: null });

    void (async () => {
      try {
        const audio = await active.stop();
        if (attempt !== run) {
          return;
        }
        recording = null;
        set({ phase: { status: "transcribing" }, error: null });

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

        // The words stop here. Nothing reaches the tutor until `ask`.
        inFlight = null;
        set({ phase: { status: "confirming", transcript }, error: null });
      } catch (caught) {
        if (attempt === run) {
          fail(caught);
        }
      }
    })();
  };

  const edit = (transcript: string) => {
    if (state.phase.status !== "confirming") {
      return;
    }
    // Typing is the student acting on whatever went wrong, so the complaint
    // goes with the keystroke rather than sitting over the fix.
    set({ phase: { status: "confirming", transcript }, error: null });
  };

  const ask = () => {
    if (state.phase.status !== "confirming") {
      return;
    }
    const reviewing = state.phase.transcript;
    const question = reviewing.trim();
    if (!question) {
      set({
        phase: { status: "confirming", transcript: reviewing },
        error: "There is nothing to ask yet.",
      });
      return;
    }
    if (question.length > MAX_TRANSCRIPT_CHARS) {
      set({
        phase: { status: "confirming", transcript: reviewing },
        error: `Questions are limited to ${MAX_TRANSCRIPT_CHARS} characters.`,
      });
      return;
    }

    const attempt = run;
    set({ phase: { status: "submitting", transcript: question }, error: null });

    void (async () => {
      try {
        await submit(question);
        if (attempt !== run) {
          return;
        }
        teardown();
        set(IDLE);
      } catch (caught) {
        if (attempt !== run) {
          return;
        }
        // The question survives a tutor failure: it was already correct, and
        // retyping it would be the interface's fault rather than the model's.
        set({
          phase: { status: "confirming", transcript: question },
          error: messageFor(caught),
        });
      }
    })();
  };

  const cancel = () => {
    teardown();
    set(IDLE);
  };

  const rerecord = () => {
    if (state.phase.status !== "confirming") {
      return;
    }
    cancel();
    start();
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
    edit,
    ask,
    rerecord,
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
