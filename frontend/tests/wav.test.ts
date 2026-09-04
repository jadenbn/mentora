/**
 * The audio format seam.
 *
 * The browser re-encodes because MediaRecorder's container is browser-dependent
 * and the transcription provider documents neither WebM nor MP4. Everything the
 * backend's signature check and the provider rely on is in this header.
 */

import { describe, expect, it } from "vitest";
import { encodeWav, resampleTo, toMono, WAV_SAMPLE_RATE } from "@/lib/voice/wav";
import { MAX_RECORDING_MS } from "@/lib/voice/voiceCapture";

async function headerOf(blob: Blob): Promise<DataView> {
  return new DataView(await blob.arrayBuffer());
}

const ascii = (view: DataView, offset: number, length: number) =>
  String.fromCharCode(
    ...Array.from({ length }, (_, index) => view.getUint8(offset + index)),
  );

const fakeBuffer = (channels: number[][]): AudioBuffer =>
  ({
    numberOfChannels: channels.length,
    length: channels[0].length,
    getChannelData: (index: number) => Float32Array.from(channels[index]),
  }) as unknown as AudioBuffer;

describe("encodeWav", () => {
  it("writes the RIFF/WAVE signature the backend sniffs for", async () => {
    const view = await headerOf(encodeWav(Float32Array.from([0, 0]), 16_000));

    expect(ascii(view, 0, 4)).toBe("RIFF");
    expect(ascii(view, 8, 4)).toBe("WAVE");
  });

  it("declares 16-bit mono PCM at the sample rate it was given", async () => {
    const view = await headerOf(encodeWav(Float32Array.from([0]), 16_000));

    expect(view.getUint16(20, true)).toBe(1); // uncompressed PCM
    expect(view.getUint16(22, true)).toBe(1); // one channel
    expect(view.getUint32(24, true)).toBe(16_000);
    expect(view.getUint16(34, true)).toBe(16); // bits per sample
  });

  it("reports the rate the decoder actually produced, not the one requested", async () => {
    // A browser that ignores the resample request must still yield a file that
    // plays back at the right speed.
    const view = await headerOf(encodeWav(Float32Array.from([0]), 48_000));

    expect(view.getUint32(24, true)).toBe(48_000);
  });

  it("sizes both length fields to the samples it was given", async () => {
    const view = await headerOf(encodeWav(new Float32Array(10), 16_000));

    expect(view.getUint32(40, true)).toBe(20); // data chunk: 10 samples x 2 bytes
    expect(view.getUint32(4, true)).toBe(56); // whole file after the first 8 bytes
  });

  it("converts float samples to signed 16-bit", async () => {
    const view = await headerOf(encodeWav(Float32Array.from([0, 1, -1]), 16_000));

    expect(view.getInt16(44, true)).toBe(0);
    expect(view.getInt16(46, true)).toBe(32_767);
    expect(view.getInt16(48, true)).toBe(-32_767);
  });

  it("clamps samples outside [-1, 1] rather than wrapping them", async () => {
    const view = await headerOf(encodeWav(Float32Array.from([4, -4]), 16_000));

    expect(view.getInt16(44, true)).toBe(32_767);
    expect(view.getInt16(46, true)).toBe(-32_767);
  });
});

describe("resampleTo", () => {
  it("leaves audio that already arrived at the target rate alone", () => {
    const samples = Float32Array.from([0.1, 0.2, 0.3]);
    expect(resampleTo(samples, 16_000, 16_000)).toBe(samples);
  });

  it("brings 48 kHz down to a third as many samples", () => {
    const samples = new Float32Array(48_000);
    expect(resampleTo(samples, 48_000, 16_000)).toHaveLength(16_000);
  });

  it("averages each source window rather than dropping samples", () => {
    // Decimating instead would fold everything above 8 kHz back into the
    // speech as aliasing, which is the band a transcriber listens to.
    const resampled = resampleTo(Float32Array.from([0, 3, 6, 9, 12, 15]), 48_000, 16_000);

    expect(Array.from(resampled)).toEqual([3, 12]);
  });

  it("handles a rate that is not a whole multiple", () => {
    expect(resampleTo(new Float32Array(44_100), 44_100, 16_000)).toHaveLength(16_000);
  });

  it("has nothing to do with an empty recording", () => {
    expect(resampleTo(new Float32Array(0), 48_000, 16_000)).toHaveLength(0);
  });
});

describe("the upload bound", () => {
  //: backend/app/api/voice.py. Pinned there too, so a change on either side
  //: shows up as a failing test rather than a 413 in front of a student.
  const SERVER_CAP_BYTES = 5 * 1024 * 1024;

  it("keeps the longest recording the interface allows inside the server cap", () => {
    const samples = (MAX_RECORDING_MS / 1_000) * WAV_SAMPLE_RATE;
    const wav = encodeWav(new Float32Array(samples), WAV_SAMPLE_RATE);

    expect(wav.size).toBeLessThan(SERVER_CAP_BYTES);
  });

  it("would not have fit had the decoder's 48 kHz been trusted", () => {
    // Why resampleTo is enforced rather than assumed: this is the size the
    // same recording reaches when a browser ignores the resample request.
    const unresampled = (MAX_RECORDING_MS / 1_000) * 48_000 * 2;

    expect(unresampled).toBeGreaterThan(SERVER_CAP_BYTES);
  });
});

describe("toMono", () => {
  it("passes a single channel through untouched", () => {
    expect(Array.from(toMono(fakeBuffer([[0.5, -0.5]])))).toEqual([0.5, -0.5]);
  });

  it("averages multiple channels", () => {
    expect(Array.from(toMono(fakeBuffer([[1, 0], [0, 1]])))).toEqual([0.5, 0.5]);
  });
});
