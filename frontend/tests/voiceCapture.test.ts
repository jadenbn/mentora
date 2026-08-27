/**
 * The recording lifecycle, as a state machine.
 *
 * Two things are worth the most here. First, that every abandoned path — a
 * cancel, a failure, an unmount mid-flight — releases the microphone and
 * cannot still reach the tutor afterwards. Second, that the student cannot
 * start two recordings or submit one question twice.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createVoiceCapture,
  MAX_RECORDING_MS,
  type VoiceCapture,
} from "@/lib/voice/voiceCapture";
import { MicrophonePermissionError } from "@/lib/voice/microphone";

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

/** Drive a capture from idle to recording. */
async function record(capture: VoiceCapture) {
  capture.start();
  await settle();
  return capture;
}

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => vi.useRealTimers());

describe("the happy path", () => {
  it("walks idle -> recording -> submitting -> idle", async () => {
    const { capture, submit } = harness();

    expect(capture.getState().status).toBe("idle");
    await record(capture);
    expect(capture.getState().status).toBe("recording");

    capture.stop();
    await settle();

    expect(submit).toHaveBeenCalledWith("why can't I cancel the x?");
    expect(capture.getState()).toEqual({ status: "idle", error: null, startedAt: null });
  });

  it("times the recording so the student can see how long they have talked", async () => {
    const { capture } = harness();
    await record(capture);
    expect(capture.getState().startedAt).toBeTypeOf("number");
  });

  it("trims the transcript before it reaches the tutor", async () => {
    const { capture, submit } = harness({ transcribe: async () => "  why is this wrong? " });
    await record(capture);
    capture.stop();
    await settle();
    expect(submit).toHaveBeenCalledWith("why is this wrong?");
  });

  it("sends the encoded audio, not the raw recording", async () => {
    const transcribe = vi.fn(async (_audio: Blob, _signal: AbortSignal) => "hello");
    const { capture } = harness({ transcribe });
    await record(capture);
    capture.stop();
    await settle();
    expect(transcribe.mock.calls[0][0]).toBe(WAV);
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

  it("ignores a second stop while the first is still in flight", async () => {
    const { capture, submit } = harness();
    await record(capture);

    capture.stop();
    capture.stop();
    await settle();

    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("ignores stop when nothing is being recorded", async () => {
    const { capture, submit } = harness();
    capture.stop();
    await settle();
    expect(submit).not.toHaveBeenCalled();
  });
});

describe("cancelling", () => {
  it("releases the microphone and returns to idle", async () => {
    const { capture, cancel } = harness();
    await record(capture);

    capture.cancel();

    expect(cancel).toHaveBeenCalled();
    expect(capture.getState()).toEqual({ status: "idle", error: null, startedAt: null });
  });

  it("keeps a cancelled recording away from the tutor", async () => {
    let release!: (transcript: string) => void;
    const { capture, submit } = harness({
      transcribe: () => new Promise((resolve) => (release = resolve)),
    });
    await record(capture);
    capture.stop();
    await settle();
    expect(capture.getState().status).toBe("transcribing");

    capture.cancel();
    release("too late");
    await settle();

    expect(submit).not.toHaveBeenCalled();
    expect(capture.getState().status).toBe("idle");
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
    expect(capture.getState().status).toBe("idle");
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
    expect(capture.getState().status).toBe("recording");
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
});

describe("the recording limit", () => {
  it("stops itself rather than leaving a microphone open", async () => {
    const { capture, submit } = harness();
    await record(capture);

    vi.advanceTimersByTime(MAX_RECORDING_MS);
    await settle();

    expect(submit).toHaveBeenCalledTimes(1);
    expect(capture.getState().status).toBe("idle");
  });

  it("does not fire after the student stopped on their own", async () => {
    const { capture, submit } = harness();
    await record(capture);

    capture.stop();
    await settle();
    vi.advanceTimersByTime(MAX_RECORDING_MS * 2);
    await settle();

    expect(submit).toHaveBeenCalledTimes(1);
  });
});

describe("failures", () => {
  const failsWith = async (over: Parameters<typeof harness>[0]) => {
    const { capture, ...rest } = harness(over);
    await record(capture);
    if (capture.getState().status === "recording") {
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

    expect(capture.getState().status).toBe("idle");
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
  });

  it("reports a recording that held no words", async () => {
    const { capture, submit } = await failsWith({ transcribe: async () => "   " });

    expect(submit).not.toHaveBeenCalled();
    expect(capture.getState().error).toMatch(/did not catch/i);
  });

  it("reports a tutor failure without swallowing it", async () => {
    const { capture } = await failsWith({
      submit: async () => {
        throw new Error("The tutor is temporarily unavailable.");
      },
    });
    expect(capture.getState().error).toBe("The tutor is temporarily unavailable.");
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
