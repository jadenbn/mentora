const PNG_HEADER_BYTES = 24;
const PNG_SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10] as const;

export interface PngDimensions {
  width: number;
  height: number;
}

/** Read the encoded PNG dimensions from the IHDR chunk. */
export async function readPngDimensions(blob: Blob): Promise<PngDimensions> {
  const header = new Uint8Array(
    await blob.slice(0, PNG_HEADER_BYTES).arrayBuffer(),
  );
  if (header.length < PNG_HEADER_BYTES) {
    throw new Error("The canvas export did not contain a complete PNG header.");
  }

  const hasPngSignature = PNG_SIGNATURE.every(
    (byte, index) => header[index] === byte,
  );
  const hasIhdrChunk =
    header[12] === 73 &&
    header[13] === 72 &&
    header[14] === 68 &&
    header[15] === 82;
  if (!hasPngSignature || !hasIhdrChunk) {
    throw new Error("The canvas export was not a valid PNG image.");
  }

  const view = new DataView(header.buffer, header.byteOffset, header.byteLength);
  const width = view.getUint32(16, false);
  const height = view.getUint32(20, false);
  if (width === 0 || height === 0) {
    throw new Error("The canvas export has invalid image dimensions.");
  }

  return { width, height };
}
