/**
 * Recorded audio -> 16 kHz mono WAV.
 *
 * MediaRecorder's container is browser-dependent: Safari produces AAC in MP4,
 * Chrome Opus in WebM, and the transcription provider documents neither.
 * Re-encoding here means one format crosses the wire, so the backend verifies
 * a single signature and the provider never has to guess at a container.
 *
 * Mono at 16 kHz is what speech recognition uses anyway, and it bounds the
 * upload: the longest recording the interface allows is about 1.9 MB, well
 * inside the server's cap. Decoding is asked to resample, but a browser that
 * ignores the request would hand back 48 kHz and blow through that bound, so
 * the rate is enforced here rather than assumed.
 */

/** What the decoder is asked for. Speech carries nothing above 8 kHz. */
export const WAV_SAMPLE_RATE = 16_000;

const WAV_HEADER_BYTES = 44;
const BYTES_PER_SAMPLE = 2;

export class AudioEncodingError extends Error {
  constructor() {
    super("That recording could not be read.");
    this.name = "AudioEncodingError";
  }
}

/** Re-encode one MediaRecorder blob as WAV. */
export async function encodeRecordingAsWav(recording: Blob): Promise<Blob> {
  let decoded: AudioBuffer;
  try {
    const context = new OfflineAudioContext(1, 1, WAV_SAMPLE_RATE);
    decoded = await context.decodeAudioData(await recording.arrayBuffer());
  } catch {
    // A container the browser recorded but cannot decode, or an empty blob.
    // The provider error would be far less useful than saying so here.
    throw new AudioEncodingError();
  }
  return encodeWav(
    resampleTo(toMono(decoded), decoded.sampleRate, WAV_SAMPLE_RATE),
    WAV_SAMPLE_RATE,
  );
}

/**
 * Bring samples to `toRate`, averaging each source window rather than picking
 * one sample from it.
 *
 * The averaging is the point: dropping two samples in three from 48 kHz would
 * fold everything above 8 kHz back into the speech as aliasing noise, which is
 * exactly the band a transcriber listens to. This is a crude low-pass, but it
 * is a low-pass, and it only runs when the decoder declined to resample.
 */
export function resampleTo(
  samples: Float32Array,
  fromRate: number,
  toRate: number,
): Float32Array {
  if (fromRate === toRate || samples.length === 0) {
    return samples;
  }
  const ratio = fromRate / toRate;
  const resampled = new Float32Array(Math.max(1, Math.round(samples.length / ratio)));
  for (let index = 0; index < resampled.length; index += 1) {
    const start = Math.min(samples.length - 1, Math.floor(index * ratio));
    const end = Math.min(samples.length, Math.max(start + 1, Math.floor((index + 1) * ratio)));
    let total = 0;
    for (let source = start; source < end; source += 1) {
      total += samples[source];
    }
    resampled[index] = total / (end - start);
  }
  return resampled;
}

/** Average the channels: a student at a whiteboard is one mono source. */
export function toMono(buffer: AudioBuffer): Float32Array {
  const channels = Array.from({ length: buffer.numberOfChannels }, (_, index) =>
    buffer.getChannelData(index),
  );
  if (channels.length === 1) {
    return channels[0];
  }
  const mono = new Float32Array(buffer.length);
  for (let sample = 0; sample < mono.length; sample += 1) {
    let total = 0;
    for (const channel of channels) {
      total += channel[sample];
    }
    mono[sample] = total / channels.length;
  }
  return mono;
}

/** Wrap PCM samples in a canonical 16-bit mono RIFF/WAVE file. */
export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const dataBytes = samples.length * BYTES_PER_SAMPLE;
  const buffer = new ArrayBuffer(WAV_HEADER_BYTES + dataBytes);
  const view = new DataView(buffer);

  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true); // PCM format chunk length
  view.setUint16(20, 1, true); // uncompressed PCM
  view.setUint16(22, 1, true); // one channel
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * BYTES_PER_SAMPLE, true); // byte rate
  view.setUint16(32, BYTES_PER_SAMPLE, true); // block align
  view.setUint16(34, 8 * BYTES_PER_SAMPLE, true); // bits per sample
  writeAscii(view, 36, "data");
  view.setUint32(40, dataBytes, true);

  for (let index = 0; index < samples.length; index += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[index] || 0));
    view.setInt16(
      WAV_HEADER_BYTES + index * BYTES_PER_SAMPLE,
      Math.round(clamped * 0x7fff),
      true,
    );
  }

  return new Blob([buffer], { type: "audio/wav" });
}

function writeAscii(view: DataView, offset: number, text: string): void {
  for (let index = 0; index < text.length; index += 1) {
    view.setUint8(offset + index, text.charCodeAt(index));
  }
}
