import assert from "node:assert/strict";
import test from "node:test";

import type { Editor, TLShapeId } from "tldraw";
import {
  buildCanvasContext,
  captureCanvasForAnalysis,
} from "./capture.ts";

function pngHeader(width: number, height: number): Blob {
  const bytes = new Uint8Array(24);
  bytes.set([137, 80, 78, 71, 13, 10, 26, 10]);
  bytes.set([73, 72, 68, 82], 12);
  const view = new DataView(bytes.buffer);
  view.setUint32(16, width, false);
  view.setUint32(20, height, false);
  return new Blob([bytes], { type: "image/png" });
}

test("analysis capture excludes AI shapes from pixels, bounds, and context", async () => {
  const systemId = "shape:problem" as TLShapeId;
  const studentId = "shape:student" as TLShapeId;
  const aiId = "shape:ai" as TLShapeId;
  const shapes = new Map([
    [systemId, { id: systemId, type: "text", meta: { owner: "system" }, props: { text: "Problem" } }],
    [studentId, { id: studentId, type: "draw", meta: { owner: "student" }, props: {} }],
    [aiId, { id: aiId, type: "text", meta: { owner: "ai" }, props: { text: "Old hint" } }],
  ]);
  let exportedIds: TLShapeId[] = [];
  let boundedIds: TLShapeId[] = [];

  const fakeEditor = {
    getCurrentPageShapeIds: () => new Set(shapes.keys()),
    getShape: (id: TLShapeId) => shapes.get(id),
    getShapesPageBounds: (ids: TLShapeId[]) => {
      boundedIds = ids;
      return { x: 10, y: 20, w: 200, h: 100 };
    },
    toImage: async (ids: TLShapeId[]) => {
      exportedIds = ids;
      return { blob: pngHeader(1000, 500) };
    },
    getShapePageBounds: (shape: { id: TLShapeId }) =>
      shape.id === systemId
        ? { x: 10, y: 20, w: 80, h: 20 }
        : { x: 50, y: 60, w: 100, h: 40 },
    getViewportPageBounds: () => null,
    getZoomLevel: () => 1,
  } as unknown as Editor;

  const capture = await captureCanvasForAnalysis(fakeEditor);
  assert.ok(capture);
  assert.deepEqual(exportedIds, [systemId, studentId]);
  assert.deepEqual(boundedIds, [systemId, studentId]);
  assert.deepEqual(capture.shapeIds, [systemId, studentId]);
  assert.deepEqual(
    buildCanvasContext(fakeEditor, capture).shapes.map((shape) => shape.owner),
    ["system", "student"],
  );
  assert.deepEqual(
    { width: capture.width, height: capture.height },
    { width: 1000, height: 500 },
  );
});
