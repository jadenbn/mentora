/**
 * The microphone, and nothing else.
 *
 * Owns the MediaStream and the MediaRecorder for exactly one recording, and
 * guarantees every track is stopped on stop, cancel, and failure alike — a
 * track left running is a recording indicator the student cannot turn off.
 *
 * Nothing here knows about the tutor, React, or the network. The state machine
 * that drives it lives in voiceCapture.ts.
 */

/** The browser cannot record at all: no API, or an insecure origin. */
export class MicrophoneUnsupportedError extends Error {
  constructor(message = "This browser cannot record audio.") {
    super(message);
    this.name = "MicrophoneUnsupportedError";
  }
}

/** The student, or the browser, said no. */
export class MicrophonePermissionError extends Error {
  constructor() {
    super("Microphone access is blocked. Allow it in your browser settings.");
    this.name = "MicrophonePermissionError";
  }
}

/** Permission was granted but the recording did not survive. */
export class RecordingFailedError extends Error {
  constructor(message = "The recording stopped unexpectedly.") {
    super(message);
    this.name = "RecordingFailedError";
  }
}

export interface Recording {
  /** Finish and hand back what was captured, releasing the microphone. */
  stop(): Promise<Blob>;
  /** Abandon the recording and release the microphone. Safe to call twice. */
  cancel(): void;
}

/** The browser surface this module uses, named so tests can supply their own. */
export interface MicrophoneAdapter {
  isSupported(): boolean;
  getUserMedia(): Promise<MediaStream>;
  createRecorder(stream: MediaStream): MediaRecorder;
}

export function browserMicrophone(): MicrophoneAdapter {
  return {
    isSupported: () =>
      typeof window !== "undefined" &&
      typeof window.MediaRecorder === "function" &&
      typeof navigator?.mediaDevices?.getUserMedia === "function",
    getUserMedia: () => navigator.mediaDevices.getUserMedia({ audio: true }),
    // No mimeType is requested: every browser has exactly one it will record,
    // and wav.ts re-encodes whichever that is.
    createRecorder: (stream) => new MediaRecorder(stream),
  };
}

export async function startRecording(
  microphone: MicrophoneAdapter = browserMicrophone(),
): Promise<Recording> {
  if (!microphone.isSupported()) {
    // On an insecure origin the API is simply absent, which is indistinguishable
    // from an old browser unless we look. A tablet on a plain-HTTP LAN address
    // hits this, and "use https" is the only useful thing to say about it.
    throw new MicrophoneUnsupportedError(
      typeof window !== "undefined" && window.isSecureContext === false
        ? "Voice needs a secure (https) connection."
        : undefined,
    );
  }

  let stream: MediaStream;
  try {
    stream = await microphone.getUserMedia();
  } catch (caught) {
    throw asMicrophoneError(caught);
  }

  const releaseStream = () => {
    for (const track of stream.getTracks()) {
      track.stop();
    }
  };

  let recorder: MediaRecorder;
  try {
    recorder = microphone.createRecorder(stream);
    // No timeslice: one chunk delivered at stop is all a short question needs.
    recorder.start();
  } catch {
    releaseStream();
    throw new RecordingFailedError("This browser could not start recording.");
  }

  let chunks: Blob[] = [];
  let released = false;
  let stopping: Promise<Blob> | null = null;
  let abandon: ((error: Error) => void) | null = null;

  /** Detach every callback and stop every track. Idempotent, and final. */
  const release = () => {
    if (released) {
      return;
    }
    released = true;
    recorder.ondataavailable = null;
    recorder.onstop = null;
    recorder.onerror = null;
    releaseStream();
  };

  recorder.ondataavailable = (event) => {
    if (event.data?.size) {
      chunks.push(event.data);
    }
  };

  const stop = (): Promise<Blob> => {
    // Repeated taps on Stop await the same recording rather than racing it.
    if (stopping) {
      return stopping;
    }
    stopping = new Promise<Blob>((resolve, reject) => {
      if (released) {
        reject(new RecordingFailedError("The recording was already discarded."));
        return;
      }
      abandon = reject;
      recorder.onstop = () => {
        const audio = new Blob(chunks, { type: chunks[0]?.type ?? "" });
        release();
        chunks = [];
        resolve(audio);
      };
      recorder.onerror = () => {
        release();
        chunks = [];
        reject(new RecordingFailedError());
      };
      try {
        recorder.stop();
      } catch {
        release();
        chunks = [];
        reject(new RecordingFailedError());
      }
    });
    return stopping;
  };

  const cancel = () => {
    if (released) {
      return;
    }
    const wasRecording = recorder.state !== "inactive";
    // Detach first, so a stop() already in flight can never resolve with audio
    // the student asked to throw away.
    release();
    chunks = [];
    if (wasRecording) {
      try {
        recorder.stop();
      } catch {
        // Already stopping. The tracks are released either way.
      }
    }
    abandon?.(new RecordingFailedError("The recording was cancelled."));
  };

  return { stop, cancel };
}

function asMicrophoneError(caught: unknown): Error {
  const name = (caught as { name?: string } | null)?.name;
  if (name === "NotAllowedError" || name === "SecurityError") {
    return new MicrophonePermissionError();
  }
  // NotFoundError / NotReadableError and friends: the browser can record, this
  // machine's microphone just cannot right now. Saying "unsupported" here
  // would send the student off to check the wrong thing.
  return name
    ? new RecordingFailedError("No microphone is available right now.")
    : new MicrophoneUnsupportedError();
}
