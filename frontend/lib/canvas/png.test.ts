import assert from "node:assert/strict";
import test from "node:test";

import { readPngDimensions } from "./png.ts";

function pngHeader(width: number, height: number): Blob {
  const bytes = new Uint8Array(24);
  bytes.set([137, 80, 78, 71, 13, 10, 26, 10]);
  bytes.set([73, 72, 68, 82], 12);
  const view = new DataView(bytes.buffer);
  view.setUint32(16, width, false);
  view.setUint32(20, height, false);
  return new Blob([bytes], { type: "image/png" });
}

test("PNG header dimensions override fractional logical export bounds", async () => {
  const logicalExportBounds = { width: 639.75, height: 413.125 };
  const dimensions = await readPngDimensions(pngHeader(1280, 826));

  assert.equal(Number.isInteger(logicalExportBounds.width), false);
  assert.deepEqual(dimensions, { width: 1280, height: 826 });
  assert.equal(Number.isInteger(dimensions.width), true);
  assert.equal(Number.isInteger(dimensions.height), true);
});

test("invalid PNG headers are rejected before transport", async () => {
  await assert.rejects(
    readPngDimensions(new Blob([new Uint8Array(24)])),
    /valid PNG image/,
  );
});
