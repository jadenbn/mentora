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

test("analysis capture prefers student work and falls back to the problem", async () => {
  const systemId = "shape:problem" as TLShapeId;
  const studentId = "shape:student" as TLShapeId;
  const aiId = "shape:ai" as TLShapeId;
  const shapes = new Map([
    [systemId, { id: systemId, type: "text", meta: { owner: "system" }, props: { text: "Problem" } }],
    [studentId, {
      id: studentId,
      type: "text",
      meta: { owner: "student" },
      props: {
        richText: {
          type: "doc",
          content: [{
            type: "paragraph",
            content: [{ type: "text", text: "y' = 4(3x²+1)6x" }],
          }],
        },
      },
    }],
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
  assert.deepEqual(exportedIds, [studentId]);
  assert.deepEqual(boundedIds, [studentId]);
  assert.deepEqual(capture.shapeIds, [studentId]);
  assert.deepEqual(
    { x: capture.bounds.x, y: capture.bounds.y, w: capture.bounds.w, h: capture.bounds.h },
    { x: -2, y: 8, w: 224, h: 124 },
  );
  const context = buildCanvasContext(fakeEditor, capture);
  assert.deepEqual(context.shapes.map((shape) => shape.owner), ["student"]);
  assert.equal(context.shapes[0]?.text, "y' = 4(3x²+1)6x");
  assert.deepEqual(
    { width: capture.width, height: capture.height },
    { width: 1000, height: 500 },
  );

  shapes.delete(studentId);
  const fallback = await captureCanvasForAnalysis(fakeEditor);
  assert.ok(fallback);
  assert.deepEqual(exportedIds, [systemId]);
  assert.deepEqual(boundedIds, [systemId]);
  assert.deepEqual(fallback.shapeIds, [systemId]);
});
