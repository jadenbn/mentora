/**
 * The microphone lifecycle.
 *
 * The invariant worth the most here is the boring one: no path — stop, cancel,
 * failure, or double-tap — may leave a track running. A live track is a
 * recording indicator the student cannot turn off.
 */

import { describe, expect, it, vi } from "vitest";
import {
  MicrophonePermissionError,
  MicrophoneUnsupportedError,
  RecordingFailedError,
  startRecording,
  type MicrophoneAdapter,
} from "@/lib/voice/microphone";

class FakeRecorder {
  // Starts inactive, exactly like a real one: a recorder that was constructed
  // but never started captures nothing.
  state: "recording" | "inactive" = "inactive";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;

  start() {
    this.state = "recording";
  }

  /** Real recorders flush their last chunk asynchronously; so does this one. */
  stop() {
    this.state = "inactive";
    queueMicrotask(() => {
      this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/webm" }) });
      this.onstop?.();
    });
  }

  /** The recorder failing on its own, rather than being asked to stop. */
  fail() {
    this.state = "inactive";
    this.onerror?.();
  }
}

function fakeMicrophone(
  over: Partial<MicrophoneAdapter> = {},
): { microphone: MicrophoneAdapter; tracks: { stop: ReturnType<typeof vi.fn> }[]; recorder: FakeRecorder } {
  const tracks = [{ stop: vi.fn() }, { stop: vi.fn() }];
  const recorder = new FakeRecorder();
  const microphone: MicrophoneAdapter = {
    isSupported: () => true,
    getUserMedia: async () => ({ getTracks: () => tracks }) as unknown as MediaStream,
    createRecorder: () => recorder as unknown as MediaRecorder,
    ...over,
  };
  return { microphone, tracks, recorder };
}

const stopped = (tracks: { stop: ReturnType<typeof vi.fn> }[]) =>
  tracks.every((track) => track.stop.mock.calls.length > 0);

describe("starting", () => {
  it("actually starts the recorder, not just builds one", async () => {
    const { microphone, recorder } = fakeMicrophone();
    await startRecording(microphone);
    expect(recorder.state).toBe("recording");
  });

  it("hands back a recording once permission is granted", async () => {
    const { microphone } = fakeMicrophone();
    await expect(startRecording(microphone)).resolves.toMatchObject({
      stop: expect.any(Function),
      cancel: expect.any(Function),
    });
  });

  it("refuses a browser that cannot record", async () => {
    const { microphone } = fakeMicrophone({ isSupported: () => false });
    await expect(startRecording(microphone)).rejects.toBeInstanceOf(
      MicrophoneUnsupportedError,
    );
  });

  it("names https as the problem on an insecure origin", async () => {
    // How a tablet on http://YOUR-IP:3000 fails: the API is absent rather than
    // blocked, so without this the student is told to change browsers.
    const secure = Object.getOwnPropertyDescriptor(window, "isSecureContext");
    Object.defineProperty(window, "isSecureContext", { value: false, configurable: true });
    const { microphone } = fakeMicrophone({ isSupported: () => false });

    await expect(startRecording(microphone)).rejects.toThrow(/https/i);

    if (secure) {
      Object.defineProperty(window, "isSecureContext", secure);
    }
  });

  it("reports a denied permission prompt as such", async () => {
    const denied = Object.assign(new Error("denied"), { name: "NotAllowedError" });
    const { microphone } = fakeMicrophone({
      getUserMedia: async () => {
        throw denied;
      },
    });
    await expect(startRecording(microphone)).rejects.toBeInstanceOf(
      MicrophonePermissionError,
    );
  });

  it("does not blame permissions when the hardware is the problem", async () => {
    const missing = Object.assign(new Error("no device"), { name: "NotFoundError" });
    const { microphone } = fakeMicrophone({
      getUserMedia: async () => {
        throw missing;
      },
    });
    await expect(startRecording(microphone)).rejects.toBeInstanceOf(RecordingFailedError);
  });

  it("releases the stream when the recorder itself cannot be built", async () => {
    const { microphone, tracks } = fakeMicrophone({
      createRecorder: () => {
        throw new Error("unsupported");
      },
    });
    await expect(startRecording(microphone)).rejects.toBeInstanceOf(RecordingFailedError);
    expect(stopped(tracks)).toBe(true);
  });
});

describe("stopping", () => {
  it("returns what was captured", async () => {
    const { microphone } = fakeMicrophone();
    const recording = await startRecording(microphone);
    await expect((await recording.stop()).size).toBeGreaterThan(0);
  });

  it("stops every track", async () => {
    const { microphone, tracks } = fakeMicrophone();
    const recording = await startRecording(microphone);
    await recording.stop();
    expect(stopped(tracks)).toBe(true);
  });

  it("treats a second tap as the same stop rather than a race", async () => {
    const { microphone, recorder } = fakeMicrophone();
    const recording = await startRecording(microphone);
    const spy = vi.spyOn(recorder, "stop");
    const [first, second] = await Promise.all([recording.stop(), recording.stop()]);
    expect(first).toBe(second);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("reports a recorder that fails mid-flight", async () => {
    const { microphone, recorder, tracks } = fakeMicrophone();
    const recording = await startRecording(microphone);
    const pending = recording.stop();
    recorder.fail();
    await expect(pending).rejects.toBeInstanceOf(RecordingFailedError);
    expect(stopped(tracks)).toBe(true);
  });
});

describe("cancelling", () => {
  it("stops every track", async () => {
    const { microphone, tracks } = fakeMicrophone();
    const recording = await startRecording(microphone);
    recording.cancel();
    expect(stopped(tracks)).toBe(true);
  });

  it("is safe to call twice", async () => {
    const { microphone, tracks } = fakeMicrophone();
    const recording = await startRecording(microphone);
    recording.cancel();
    recording.cancel();
    expect(tracks[0].stop).toHaveBeenCalledTimes(1);
  });

  it("abandons a stop that is already in flight", async () => {
    // Otherwise the caller waits forever on audio it asked to throw away.
    const { microphone } = fakeMicrophone({
      createRecorder: () =>
        ({ state: "recording", start: () => {}, stop: () => {} }) as unknown as MediaRecorder,
    });
    const recording = await startRecording(microphone);
    const pending = recording.stop();
    recording.cancel();
    await expect(pending).rejects.toBeInstanceOf(RecordingFailedError);
  });

  it("refuses to hand back audio after the recording was discarded", async () => {
    const { microphone } = fakeMicrophone();
    const recording = await startRecording(microphone);
    recording.cancel();
    await expect(recording.stop()).rejects.toBeInstanceOf(RecordingFailedError);
  });
});
