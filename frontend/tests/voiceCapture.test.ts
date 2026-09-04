/**
 * The recording lifecycle, as a state machine.
 *
 * Three things are worth the most here. First, that every abandoned path — a
 * cancel, a failure, an unmount mid-flight — releases the microphone and
 * cannot still reach the tutor afterwards. Second, that the student cannot
 * start two recordings or submit one question twice. Third, that transcribing
 * asks the tutor nothing: the words wait for review, and only `ask` spends a
 * tutor call.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createVoiceCapture,
  MAX_RECORDING_MS,
  type VoiceCapture,
} from "@/lib/voice/voiceCapture";
import { MicrophonePermissionError } from "@/lib/voice/microphone";
import { MAX_TRANSCRIPT_CHARS } from "@/types/voice";

const AUDIO = new Blob(["raw"], { type: "audio/webm" });
const WAV = new Blob(["wav"], { type: "audio/wav" });

/** Resolves once every already-queued microtask has run. */
const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

function harness(
  over: {
    startRecording?: () => Promise<{ stop: () => Promise<Blob>; cancel: () => void }>;
    encode?: (recording: Blob) => Promise<Blob>;
    transcribe?: (audio: Blob, signal: AbortSignal) => Promise<string>;
    submit?: (transcript: string) => Promise<void>;
  } = {},
) {
  const cancel = vi.fn();
  const stop = vi.fn(async () => AUDIO);
  const submit = vi.fn(async () => {});
  const capture = createVoiceCapture({
    submit: over.submit ?? submit,
    deps: {
      startRecording: over.startRecording ?? (async () => ({ stop, cancel })),
      encode: over.encode ?? (async () => WAV),
      transcribe: over.transcribe ?? (async () => "why can't I cancel the x?"),
    },
  });
  return { capture, cancel, stop, submit };
}

const status = (capture: VoiceCapture) => capture.getState().phase.status;

/** The words under review, or null when there are none. */
function reviewing(capture: VoiceCapture): string | null {
  const phase = capture.getState().phase;
  return phase.status === "confirming" || phase.status === "submitting"
    ? phase.transcript
    : null;
}

/** Drive a capture from idle to recording. */
async function record(capture: VoiceCapture) {
  capture.start();
  await settle();
  return capture;
}

/** Drive a capture all the way to the confirmation step. */
async function confirmable(capture: VoiceCapture) {
  await record(capture);
  capture.stop();
  await settle();
  return capture;
}

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => vi.useRealTimers());

describe("the happy path", () => {
  it("walks idle -> recording -> confirming -> submitting -> idle", async () => {
    const { capture, submit } = harness();

    expect(status(capture)).toBe("idle");
    await record(capture);
    expect(status(capture)).toBe("recording");

    capture.stop();
    await settle();
    expect(status(capture)).toBe("confirming");
    expect(submit).not.toHaveBeenCalled();

    capture.ask();
    await settle();

    expect(submit).toHaveBeenCalledWith("why can't I cancel the x?");
    expect(capture.getState()).toEqual({ phase: { status: "idle" }, error: null });
  });

  it("times the recording so the student can see how long they have talked", async () => {
    const { capture } = harness();
    await record(capture);
    const phase = capture.getState().phase;
    expect(phase.status === "recording" && phase.startedAt).toBeTypeOf("number");
  });

  it("shows the student what the model heard", async () => {
    const capture = await confirmable(harness().capture);
    expect(reviewing(capture)).toBe("why can't I cancel the x?");
  });

  it("trims the transcript before it reaches review", async () => {
    const { capture } = harness({ transcribe: async () => "  why is this wrong? " });
    await confirmable(capture);
    expect(reviewing(capture)).toBe("why is this wrong?");
  });

  it("sends the encoded audio, not the raw recording", async () => {
    const transcribe = vi.fn(async (_audio: Blob, _signal: AbortSignal) => "hello");
    const { capture } = harness({ transcribe });
    await confirmable(capture);
    expect(transcribe.mock.calls[0][0]).toBe(WAV);
  });
});

describe("confirming before anything is asked", () => {
  it("does not call the tutor merely because a transcript arrived", async () => {
    const { capture, submit } = harness();
    await confirmable(capture);

    // The whole point of the step: the words exist and have gone nowhere.
    expect(status(capture)).toBe("confirming");
    expect(submit).not.toHaveBeenCalled();
  });

  it("sends the student's correction rather than what was heard", async () => {
    const { capture, submit } = harness();
    await confirmable(capture);

    capture.edit("why can't I cancel the x squared?");
    capture.ask();
    await settle();

    expect(submit).toHaveBeenCalledWith("why can't I cancel the x squared?");
  });

  it("trims the edited question before sending it", async () => {
    const { capture, submit } = harness();
    await confirmable(capture);

    capture.edit("   why is this wrong?  ");
    capture.ask();
    await settle();

    expect(submit).toHaveBeenCalledWith("why is this wrong?");
  });

  it("refuses an emptied question instead of spending a tutor call", async () => {
    const { capture, submit } = harness();
    await confirmable(capture);

    capture.edit("   ");
    capture.ask();
    await settle();

    expect(submit).not.toHaveBeenCalled();
    expect(status(capture)).toBe("confirming");
    expect(capture.getState().error).toMatch(/nothing to ask/i);
  });

  it("refuses a question longer than the tutor endpoint accepts", async () => {
    // Refusing here is a readable message; sending it is a 422.
    const { capture, submit } = harness();
    await confirmable(capture);

    capture.edit("a".repeat(MAX_TRANSCRIPT_CHARS + 1));
    capture.ask();
    await settle();

    expect(submit).not.toHaveBeenCalled();
    expect(capture.getState().error).toMatch(/limited to/i);
  });

  it("accepts a question exactly at the limit", async () => {
    const { capture, submit } = harness();
    await confirmable(capture);

    capture.edit("a".repeat(MAX_TRANSCRIPT_CHARS));
    capture.ask();
    await settle();

    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("ignores ask when there is nothing under review", async () => {
    const { capture, submit } = harness();
    capture.ask();
    await settle();
    expect(submit).not.toHaveBeenCalled();
  });

  it("clears a refusal as soon as the student starts fixing it", async () => {
    const { capture } = harness();
    await confirmable(capture);
    capture.edit("   ");
    capture.ask();
    await settle();
    expect(capture.getState().error).not.toBeNull();

    capture.edit("why is this wrong?");

    expect(capture.getState().error).toBeNull();
  });

  it("ignores an edit that arrives outside review", async () => {
    const { capture } = harness();
    await record(capture);

    capture.edit("typed while recording");

    expect(status(capture)).toBe("recording");
  });

  it("ignores a second ask while the first is still in flight", async () => {
    const { capture, submit } = harness();
    await confirmable(capture);

    capture.ask();
    capture.ask();
    await settle();

    expect(submit).toHaveBeenCalledTimes(1);
  });
});

describe("rerecording", () => {
  it("throws the transcript away and opens the microphone again", async () => {
    const startRecording = vi.fn(async () => ({ stop: async () => AUDIO, cancel: () => {} }));
    const { capture } = harness({ startRecording });
    await confirmable(capture);

    capture.rerecord();
    await settle();

    expect(startRecording).toHaveBeenCalledTimes(2);
    expect(status(capture)).toBe("recording");
    expect(reviewing(capture)).toBeNull();
  });

  it("does not reopen or leak the recording it replaces", async () => {
    // The first recording was already closed by stop(); rerecord has to open a
    // second one rather than reviving or abandoning the first.
    const opened: { stopped: boolean }[] = [];
    const { capture } = harness({
      startRecording: async () => {
        const opening = { stopped: false };
        opened.push(opening);
        return {
          stop: async () => {
            opening.stopped = true;
            return AUDIO;
          },
          cancel: () => {},
        };
      },
    });
    await confirmable(capture);

    capture.rerecord();
    await settle();

    expect(opened).toHaveLength(2);
    expect(opened[0].stopped).toBe(true);
    expect(status(capture)).toBe("recording");
  });

  it("clears a failure the student is retrying past", async () => {
    const { capture } = harness({
      submit: async () => {
        throw new Error("The tutor is temporarily unavailable.");
      },
    });
    await confirmable(capture);
    capture.ask();
    await settle();
    expect(capture.getState().error).not.toBeNull();

    capture.rerecord();
    await settle();

    expect(capture.getState().error).toBeNull();
  });

  it("does nothing outside review", async () => {
    const startRecording = vi.fn(async () => ({ stop: async () => AUDIO, cancel: () => {} }));
    const { capture } = harness({ startRecording });
    await record(capture);

    capture.rerecord();
    await settle();

    expect(startRecording).toHaveBeenCalledTimes(1);
  });
});

describe("guards against doing it twice", () => {
  it("ignores a second start while already recording", async () => {
    const startRecording = vi.fn(async () => ({ stop: async () => AUDIO, cancel: () => {} }));
    const { capture } = harness({ startRecording });

    await record(capture);
    capture.start();
    capture.start();
    await settle();

    expect(startRecording).toHaveBeenCalledTimes(1);
  });

  it("ignores a start while a question is waiting to be reviewed", async () => {
    const startRecording = vi.fn(async () => ({ stop: async () => AUDIO, cancel: () => {} }));
    const { capture } = harness({ startRecording });
    await confirmable(capture);

    capture.start();
    await settle();

    expect(startRecording).toHaveBeenCalledTimes(1);
    expect(status(capture)).toBe("confirming");
  });

  it("ignores a second stop while the first is still in flight", async () => {
    const transcribe = vi.fn(async () => "why can't I cancel the x?");
    const { capture } = harness({ transcribe });
    await record(capture);

    capture.stop();
    capture.stop();
    await settle();

    expect(transcribe).toHaveBeenCalledTimes(1);
  });

  it("ignores stop when nothing is being recorded", async () => {
    const transcribe = vi.fn(async () => "hello");
    const { capture } = harness({ transcribe });
    capture.stop();
    await settle();
    expect(transcribe).not.toHaveBeenCalled();
  });
});

describe("cancelling", () => {
  it("releases the microphone and returns to idle", async () => {
    const { capture, cancel } = harness();
    await record(capture);

    capture.cancel();

    expect(cancel).toHaveBeenCalled();
    expect(capture.getState()).toEqual({ phase: { status: "idle" }, error: null });
  });

  it("keeps a cancelled recording away from the tutor", async () => {
    let release!: (transcript: string) => void;
    const { capture, submit } = harness({
      transcribe: () => new Promise((resolve) => (release = resolve)),
    });
    await record(capture);
    capture.stop();
    await settle();
    expect(status(capture)).toBe("transcribing");

    capture.cancel();
    release("too late");
    await settle();

    expect(submit).not.toHaveBeenCalled();
    expect(status(capture)).toBe("idle");
  });

  it("discards a question the student decided not to ask", async () => {
    const { capture, submit } = harness();
    await confirmable(capture);

    capture.cancel();

    expect(status(capture)).toBe("idle");
    expect(reviewing(capture)).toBeNull();
    expect(submit).not.toHaveBeenCalled();
  });

  it("keeps a question cancelled mid-submit from landing afterwards", async () => {
    let release!: () => void;
    const { capture } = harness({
      submit: () => new Promise<void>((resolve) => (release = resolve)),
    });
    await confirmable(capture);
    capture.ask();
    await settle();
    expect(status(capture)).toBe("submitting");

    capture.cancel();
    release();
    await settle();

    expect(status(capture)).toBe("idle");
  });

  it("aborts the transcription request rather than letting it finish", async () => {
    const seen: AbortSignal[] = [];
    const { capture } = harness({
      transcribe: (_audio, signal) => {
        seen.push(signal);
        return new Promise(() => {});
      },
    });
    await record(capture);
    capture.stop();
    await settle();

    capture.cancel();

    expect(seen[0].aborted).toBe(true);
  });

  it("releases a microphone granted after the student had already cancelled", async () => {
    // The permission prompt can outlive the student's patience.
    const cancel = vi.fn();
    let grant!: (recording: { stop: () => Promise<Blob>; cancel: () => void }) => void;
    const { capture } = harness({
      startRecording: () => new Promise((resolve) => (grant = resolve)),
    });

    capture.start();
    capture.cancel();
    grant({ stop: async () => AUDIO, cancel });
    await settle();

    expect(cancel).toHaveBeenCalled();
    expect(status(capture)).toBe("idle");
  });
});

describe("mounting and unmounting", () => {
  it("releases the microphone when the component goes away", async () => {
    const { capture, cancel } = harness();
    const unmount = capture.mount();
    await record(capture);

    unmount();

    expect(cancel).toHaveBeenCalled();
  });

  it("refuses to start again once torn down", async () => {
    const startRecording = vi.fn(async () => ({ stop: async () => AUDIO, cancel: () => {} }));
    const { capture } = harness({ startRecording });

    capture.mount()();
    capture.start();
    await settle();

    expect(startRecording).not.toHaveBeenCalled();
  });

  it("survives the setup, teardown, setup that Strict Mode replays", async () => {
    // The machine outlives the effect, so a one-way teardown would leave the
    // microphone inert for the life of the page in development.
    const startRecording = vi.fn(async () => ({ stop: async () => AUDIO, cancel: () => {} }));
    const { capture } = harness({ startRecording });

    capture.mount()();
    capture.mount();
    capture.start();
    await settle();

    expect(startRecording).toHaveBeenCalledTimes(1);
    expect(status(capture)).toBe("recording");
  });

  it("keeps work in flight at unmount away from the tutor", async () => {
    let release!: (transcript: string) => void;
    const { capture, submit } = harness({
      transcribe: () => new Promise((resolve) => (release = resolve)),
    });
    const unmount = capture.mount();
    await record(capture);
    capture.stop();
    await settle();

    unmount();
    release("too late");
    await settle();

    expect(submit).not.toHaveBeenCalled();
  });

  it("drops a question still under review at unmount", async () => {
    const { capture, submit } = harness();
    const unmount = capture.mount();
    await confirmable(capture);

    unmount();
    capture.ask();
    await settle();

    expect(status(capture)).toBe("idle");
    expect(submit).not.toHaveBeenCalled();
  });
});

describe("the recording limit", () => {
  it("stops itself rather than leaving a microphone open", async () => {
    const { capture } = harness();
    await record(capture);

    vi.advanceTimersByTime(MAX_RECORDING_MS);
    await settle();

    // Stopping is not asking: the student still reviews what was captured.
    expect(status(capture)).toBe("confirming");
  });

  it("does not fire after the student stopped on their own", async () => {
    const transcribe = vi.fn(async () => "why can't I cancel the x?");
    const { capture } = harness({ transcribe });
    await confirmable(capture);

    vi.advanceTimersByTime(MAX_RECORDING_MS * 2);
    await settle();

    expect(transcribe).toHaveBeenCalledTimes(1);
    expect(status(capture)).toBe("confirming");
  });
});

describe("failures", () => {
  const failsWith = async (over: Parameters<typeof harness>[0]) => {
    const { capture, ...rest } = harness(over);
    await record(capture);
    if (status(capture) === "recording") {
      capture.stop();
      await settle();
    }
    return { capture, ...rest };
  };

  it("reports a denied microphone in words the student can act on", async () => {
    const { capture } = harness({
      startRecording: async () => {
        throw new MicrophonePermissionError();
      },
    });
    capture.start();
    await settle();

    expect(status(capture)).toBe("idle");
    expect(capture.getState().error).toMatch(/browser settings/i);
  });

  it("reports a recording that could not be encoded", async () => {
    const { capture } = await failsWith({
      encode: async () => {
        throw new Error("That recording could not be read.");
      },
    });
    expect(capture.getState().error).toBe("That recording could not be read.");
  });

  it("reports a transcription failure", async () => {
    const { capture } = await failsWith({
      transcribe: async () => {
        throw new Error("Voice input is temporarily unavailable.");
      },
    });
    expect(capture.getState().error).toBe("Voice input is temporarily unavailable.");
    expect(status(capture)).toBe("idle");
  });

  it("reports a recording that held no words", async () => {
    const { capture, submit } = await failsWith({ transcribe: async () => "   " });

    expect(submit).not.toHaveBeenCalled();
    expect(capture.getState().error).toMatch(/did not catch/i);
  });

  it("keeps the question under review when the tutor fails", async () => {
    // The words were already right; retyping them would be our fault.
    const { capture } = harness({
      submit: async () => {
        throw new Error("The tutor is temporarily unavailable.");
      },
    });
    await confirmable(capture);
    capture.edit("why is this step wrong?");
    capture.ask();
    await settle();

    expect(status(capture)).toBe("confirming");
    expect(reviewing(capture)).toBe("why is this step wrong?");
    expect(capture.getState().error).toBe("The tutor is temporarily unavailable.");
  });

  it("lets the student ask again after a tutor failure", async () => {
    let attempts = 0;
    const { capture } = harness({
      submit: async () => {
        attempts += 1;
        if (attempts === 1) {
          throw new Error("The tutor is temporarily unavailable.");
        }
      },
    });
    await confirmable(capture);
    capture.ask();
    await settle();

    capture.ask();
    await settle();

    expect(attempts).toBe(2);
    expect(capture.getState()).toEqual({ phase: { status: "idle" }, error: null });
  });

  it("releases the microphone when the recorder itself fails", async () => {
    // stop() rejecting is the one failure that leaves a live recording behind,
    // so this is the path where teardown has real work to do.
    const cancel = vi.fn();
    const { capture } = harness({
      startRecording: async () => ({
        stop: async () => {
          throw new Error("The recording stopped unexpectedly.");
        },
        cancel,
      }),
    });
    await record(capture);
    capture.stop();
    await settle();

    expect(cancel).toHaveBeenCalled();
    expect(capture.getState().error).toBe("The recording stopped unexpectedly.");
  });

  it("clears a previous failure when the student tries again", async () => {
    const { capture } = await failsWith({ transcribe: async () => "" });
    expect(capture.getState().error).not.toBeNull();

    capture.start();
    await settle();

    expect(capture.getState().error).toBeNull();
  });
});
