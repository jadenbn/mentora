import { describe, expect, it } from "vitest";
import {
  buildCanvasContext,
  captureCanvasForAnalysis,
  toNormalizedBounds,
} from "@/lib/canvas/capture";
import { box, makeEditor } from "./fakeEditor";

const FRAME = box(100, 50, 800, 600);

describe("toNormalizedBounds", () => {
  it("maps a contained box into [0,1]", () => {
    expect(toNormalizedBounds(box(300, 200, 200, 150), FRAME)).toEqual({
      x: 0.25,
      y: 0.25,
      width: 0.25,
      height: 0.25,
    });
  });

  it("puts the frame's own origin at (0,0)", () => {
    const n = toNormalizedBounds(box(100, 50, 80, 60), FRAME)!;
    expect(n.x).toBe(0);
    expect(n.y).toBe(0);
  });

  it("keeps x+width and y+height within 1, which the backend enforces", () => {
    const n = toNormalizedBounds(box(820, 590, 80, 60), FRAME)!;
    expect(n.x + n.width).toBeLessThanOrEqual(1);
    expect(n.y + n.height).toBeLessThanOrEqual(1);
  });

  it("clips a box straddling the edge instead of exceeding the range", () => {
    const n = toNormalizedBounds(box(850, 600, 200, 200), FRAME)!;
    expect(n.width).toBeGreaterThan(0);
    expect(n.x + n.width).toBeCloseTo(1, 10);
  });

  it("drops a box entirely outside the frame rather than emitting a 422", () => {
    expect(toNormalizedBounds(box(2000, 2000, 10, 10), FRAME)).toBeNull();
  });

  it("drops a zero-area box, since the backend requires width and height > 0", () => {
    expect(toNormalizedBounds(box(300, 200, 0, 0), FRAME)).toBeNull();
  });

  it("returns null for a degenerate frame instead of dividing by zero", () => {
    expect(toNormalizedBounds(box(0, 0, 10, 10), box(0, 0, 0, 0))).toBeNull();
  });

  it("never emits NaN for non-finite input", () => {
    const n = toNormalizedBounds(box(Number.NaN, 0, 100, 100), FRAME);
    if (n) {
      for (const v of Object.values(n)) expect(Number.isNaN(v)).toBe(false);
    }
  });
});

describe("captureCanvasForAnalysis", () => {
  it("returns null when the page is empty, so no pointless request is made", async () => {
    const { editor } = makeEditor({ shapes: [] });
    expect(await captureCanvasForAnalysis(editor)).toBeNull();
  });

  it("returns null when the page has no measurable bounds", async () => {
    const { editor } = makeEditor({
      shapes: [{ id: "shape:a", type: "draw" }],
      pageBounds: null,
    });
    expect(await captureCanvasForAnalysis(editor)).toBeNull();
  });

  it("reports the world rectangle the image covers", async () => {
    const { editor } = makeEditor({
      shapes: [{ id: "shape:a", type: "draw" }],
      pageBounds: FRAME,
    });
    const capture = await captureCanvasForAnalysis(editor);
    expect(capture!.bounds).toBe(FRAME);
  });

  it("exports with zero padding so the image matches those bounds exactly", async () => {
    const { editor, toImageCalls } = makeEditor({
      shapes: [{ id: "shape:a", type: "draw" }],
      pageBounds: FRAME,
    });
    await captureCanvasForAnalysis(editor);
    expect(toImageCalls[0].opts).toMatchObject({
      format: "png",
      padding: 0,
      bounds: FRAME,
    });
  });

  it("scales oversized canvases down to stay under the 10 MB upload limit", async () => {
    const { editor, toImageCalls } = makeEditor({
      shapes: [{ id: "shape:a", type: "draw" }],
      pageBounds: box(0, 0, 8000, 400),
    });
    await captureCanvasForAnalysis(editor);
    expect(toImageCalls[0].opts.scale).toBeCloseTo(2048 / 8000, 10);
  });

  it("never scales a small canvas up", async () => {
    const { editor, toImageCalls } = makeEditor({
      shapes: [{ id: "shape:a", type: "draw" }],
      pageBounds: box(0, 0, 100, 80),
    });
    await captureCanvasForAnalysis(editor);
    expect(toImageCalls[0].opts.scale).toBe(1);
  });

  it("exports every shape on the page", async () => {
    const { editor, toImageCalls } = makeEditor({
      shapes: [
        { id: "shape:a", type: "draw" },
        { id: "shape:b", type: "text" },
      ],
    });
    await captureCanvasForAnalysis(editor);
    expect(toImageCalls[0].ids).toHaveLength(2);
  });

  it("returns null when the export yields no blob", async () => {
    const { editor } = makeEditor({
      shapes: [{ id: "shape:a", type: "draw" }],
      image: null,
    });
    expect(await captureCanvasForAnalysis(editor)).toBeNull();
  });
});

describe("buildCanvasContext", () => {
  const capture = { blob: new Blob(), width: 1024, height: 768, bounds: FRAME };

  it("reports the exported image dimensions, not the world size", () => {
    const { editor } = makeEditor({ shapes: [] });
    const ctx = buildCanvasContext(editor, capture);
    expect(ctx.image_width).toBe(1024);
    expect(ctx.image_height).toBe(768);
  });

  it("labels AI-authored shapes so the tutor can tell them from student work", () => {
    const { editor } = makeEditor({
      shapes: [{ id: "shape:ai", type: "text", meta: { owner: "ai" } }],
    });
    expect(buildCanvasContext(editor, capture).shapes[0].owner).toBe("ai");
  });

  it("labels problem shapes as system", () => {
    const { editor } = makeEditor({
      shapes: [{ id: "shape:p", type: "text", meta: { owner: "system" } }],
    });
    expect(buildCanvasContext(editor, capture).shapes[0].owner).toBe("system");
  });

  it("treats unmarked shapes as student work", () => {
    const { editor } = makeEditor({ shapes: [{ id: "shape:s", type: "draw" }] });
    expect(buildCanvasContext(editor, capture).shapes[0].owner).toBe("student");
  });

  it("ignores an unrecognised owner rather than forwarding it", () => {
    const { editor } = makeEditor({
      shapes: [{ id: "shape:x", type: "draw", meta: { owner: "wizard" } }],
    });
    expect(buildCanvasContext(editor, capture).shapes[0].owner).toBe("student");
  });

  it("normalizes each shape's bounds against the captured frame", () => {
    const { editor } = makeEditor({
      shapes: [
        { id: "shape:a", type: "draw", pageBounds: box(300, 200, 200, 150) },
      ],
    });
    expect(buildCanvasContext(editor, capture).shapes[0].bounds).toEqual({
      x: 0.25,
      y: 0.25,
      width: 0.25,
      height: 0.25,
    });
  });

  it("emits null bounds when a shape cannot be measured", () => {
    const { editor } = makeEditor({
      shapes: [{ id: "shape:a", type: "draw", pageBounds: null }],
    });
    expect(buildCanvasContext(editor, capture).shapes[0].bounds).toBeNull();
  });

  it("carries shape text through for grounding", () => {
    const { editor } = makeEditor({
      shapes: [{ id: "shape:t", type: "text", props: { text: "dz/dt" } }],
    });
    expect(buildCanvasContext(editor, capture).shapes[0].text).toBe("dz/dt");
  });

  it("emits null rather than an empty string when there is no text", () => {
    const { editor } = makeEditor({ shapes: [{ id: "shape:d", type: "draw" }] });
    expect(buildCanvasContext(editor, capture).shapes[0].text).toBeNull();
  });

  it("preserves shape ids so a selection can reference them", () => {
    const { editor } = makeEditor({
      shapes: [{ id: "shape:a", type: "draw" }, { id: "shape:b", type: "geo" }],
    });
    const ids = buildCanvasContext(editor, capture).shapes.map((s) => s.id);
    expect(ids).toEqual(["shape:a", "shape:b"]);
  });

  it("includes the viewport in world coordinates with the zoom level", () => {
    const { editor } = makeEditor({
      shapes: [],
      viewport: box(-50, -25, 500, 400),
      zoom: 1.5,
    });
    expect(buildCanvasContext(editor, capture).viewport).toEqual({
      x: -50,
      y: -25,
      width: 500,
      height: 400,
      zoom: 1.5,
    });
  });

  it("omits the viewport when it is unavailable", () => {
    const { editor } = makeEditor({ shapes: [], viewport: null });
    expect(buildCanvasContext(editor, capture).viewport).toBeNull();
  });
});
