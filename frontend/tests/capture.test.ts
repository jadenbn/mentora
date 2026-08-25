/**
 * Canvas capture.
 *
 * Two jobs: produce an image of the student's work, and report the world-space
 * rectangle that image covers so the renderer can map answers back onto it.
 *
 * The frame below deliberately does not start at (0,0) and is not square, so
 * an implementation that forgets the offset or the aspect ratio fails here
 * instead of passing by coincidence.
 */

import { describe, expect, it } from "vitest";
import {
  captureCanvasForAnalysis,
  collectPriorAnnotations,
  toNormalizedBounds,
} from "@/lib/canvas/capture";
import { box, makeEditor } from "./fakeEditor";

const FRAME = box(100, 200, 400, 800);

const studentShape = (id: string, bounds = box(150, 300, 100, 200)) => ({
  id,
  type: "draw",
  meta: { owner: "student" },
  pageBounds: bounds,
});

const aiShape = (id: string, bounds = box(300, 600, 100, 200)) => ({
  id,
  type: "text",
  meta: { owner: "ai", interactionId: "prior" },
  pageBounds: bounds,
});

const systemShape = (id: string) => ({
  id,
  type: "mentora-problem",
  meta: { owner: "system", problemId: "problem_1" },
  pageBounds: box(120, 220, 600, 160),
});

describe("toNormalizedBounds", () => {
  it("maps a world box onto the unit square of its frame", () => {
    expect(toNormalizedBounds(box(200, 400, 200, 400), FRAME)).toEqual({
      x: 0.25,
      y: 0.25,
      width: 0.5,
      height: 0.5,
    });
  });

  it("places a box at the frame origin at (0,0)", () => {
    const result = toNormalizedBounds(box(100, 200, 40, 80), FRAME);
    expect(result).toMatchObject({ x: 0, y: 0 });
  });

  it("clamps a box that overhangs the frame", () => {
    const result = toNormalizedBounds(box(400, 900, 400, 400), FRAME);
    expect(result!.x + result!.width).toBeLessThanOrEqual(1);
    expect(result!.y + result!.height).toBeLessThanOrEqual(1);
  });

  it("drops a box that clamps away to nothing", () => {
    // The backend refuses zero-area bounds, so sending one is a guaranteed 422.
    expect(toNormalizedBounds(box(-500, -500, 100, 100), FRAME)).toBeNull();
  });

  it("drops a box with no area to begin with", () => {
    expect(toNormalizedBounds(box(200, 400, 0, 100), FRAME)).toBeNull();
  });

  it("refuses to divide by a degenerate frame", () => {
    expect(toNormalizedBounds(box(0, 0, 10, 10), box(0, 0, 0, 100))).toBeNull();
  });
});

describe("captureCanvasForAnalysis", () => {
  it("returns nothing for an empty canvas", async () => {
    const { editor } = makeEditor({ shapes: [] });
    expect(await captureCanvasForAnalysis(editor)).toBeNull();
  });

  it("returns nothing when the page has no measurable bounds", async () => {
    const { editor } = makeEditor({ shapes: [studentShape("a")], pageBounds: null });
    expect(await captureCanvasForAnalysis(editor)).toBeNull();
  });

  it("exports the student's work", async () => {
    const { editor, toImageCalls } = makeEditor({
      shapes: [studentShape("s1"), studentShape("s2")],
    });
    await captureCanvasForAnalysis(editor);
    expect(toImageCalls[0].ids).toEqual(expect.arrayContaining(["s1", "s2"]));
  });

  it("excludes the tutor's own annotations from the image", async () => {
    // This is what makes follow-up tutoring safe. If prior AI marks are in the
    // picture, the model reads its own handwriting back as student work and
    // grades it. Excluding them makes that impossible by construction rather
    // than by asking the prompt nicely.
    const { editor, toImageCalls } = makeEditor({
      shapes: [studentShape("s1"), aiShape("ai1")],
    });
    await captureCanvasForAnalysis(editor);
    expect(toImageCalls[0].ids).toEqual(["s1"]);
  });

  it("excludes the system problem from the student image", async () => {
    const { editor, toImageCalls } = makeEditor({
      shapes: [studentShape("s1"), systemShape("problem")],
    });
    await captureCanvasForAnalysis(editor);
    expect(toImageCalls[0].ids).toEqual(["s1"]);
  });

  it("returns nothing when only tutor annotations remain", async () => {
    // Nothing of the student's left to analyze, even though the page is not empty.
    const { editor } = makeEditor({ shapes: [aiShape("ai1")] });
    expect(await captureCanvasForAnalysis(editor)).toBeNull();
  });

  it("reports the world rectangle the image covers", async () => {
    const { editor } = makeEditor({ shapes: [studentShape("s1")], pageBounds: FRAME });
    const capture = await captureCanvasForAnalysis(editor);
    expect(capture!.bounds).toEqual(FRAME);
  });

  it("scales a large canvas down to keep the upload small", async () => {
    const { editor, toImageCalls } = makeEditor({
      shapes: [studentShape("s1")],
      pageBounds: box(0, 0, 8000, 4000),
    });
    await captureCanvasForAnalysis(editor);
    expect(toImageCalls[0].opts.scale).toBeLessThan(1);
  });

  it("does not upscale a small canvas", async () => {
    const { editor, toImageCalls } = makeEditor({
      shapes: [studentShape("s1")],
      pageBounds: box(0, 0, 200, 100),
    });
    await captureCanvasForAnalysis(editor);
    expect(toImageCalls[0].opts.scale).toBe(1);
  });

  it("returns nothing when the export produces no image", async () => {
    const { editor } = makeEditor({ shapes: [studentShape("s1")], image: null });
    expect(await captureCanvasForAnalysis(editor)).toBeNull();
  });
});

describe("collectPriorAnnotations", () => {
  it("reports the tutor's earlier marks, normalized to the frame", () => {
    const { editor } = makeEditor({
      shapes: [studentShape("s1"), aiShape("ai1", box(200, 400, 200, 400))],
    });
    expect(collectPriorAnnotations(editor, FRAME)).toEqual([
      { x: 0.25, y: 0.25, width: 0.5, height: 0.5 },
    ]);
  });

  it("ignores the student's own shapes", () => {
    const { editor } = makeEditor({ shapes: [studentShape("s1"), studentShape("s2")] });
    expect(collectPriorAnnotations(editor, FRAME)).toEqual([]);
  });

  it("is empty on a first interaction", () => {
    const { editor } = makeEditor({ shapes: [studentShape("s1")] });
    expect(collectPriorAnnotations(editor, FRAME)).toEqual([]);
  });

  it("skips annotations that fall outside the captured frame", () => {
    const { editor } = makeEditor({
      shapes: [studentShape("s1"), aiShape("ai1", box(-900, -900, 50, 50))],
    });
    expect(collectPriorAnnotations(editor, FRAME)).toEqual([]);
  });
});
