/**
 * The animation driver. Frames are setTimeout-based, so fake timers make every
 * assertion deterministic.
 */

import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import type { Editor } from "tldraw";
import {
  DEFAULT_FPS,
  animateStrokes,
  sequence,
} from "@/lib/annotations/animate";
import {
  checkStrokes,
  crossStrokes,
  ellipseStroke,
  makeJitter,
  strokeLength,
} from "@/lib/annotations/geometry";

interface Recorded {
  created: Record<string, unknown>[];
  updated: Record<string, unknown>[];
  historyModes: (string | undefined)[];
}

function makeAnimEditor(): { editor: Editor; log: Recorded } {
  const log: Recorded = { created: [], updated: [], historyModes: [] };
  const editor = {
    run: (fn: () => void, opts?: { history?: string }) => {
      log.historyModes.push(opts?.history);
      fn();
    },
    createShape: (partial: Record<string, unknown>) => log.created.push(partial),
    updateShape: (partial: Record<string, unknown>) => log.updated.push(partial),
  } as unknown as Editor;
  return { editor, log };
}

const RECT = { x: 0, y: 0, w: 100, h: 60 };
const noJitter = () => 0;

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("animateStrokes", () => {
  it("creates one shape per stroke", () => {
    const { editor, log } = makeAnimEditor();
    animateStrokes(editor, crossStrokes(RECT, noJitter), {});
    vi.advanceTimersByTime(10_000);
    expect(log.created).toHaveLength(2);
  });

  it("draws nothing until the first frame runs", () => {
    const { editor, log } = makeAnimEditor();
    animateStrokes(editor, [ellipseStroke(RECT, noJitter)], {});
    expect(log.created).toHaveLength(0);
  });

  it("reveals the stroke over many frames rather than at once", () => {
    const { editor, log } = makeAnimEditor();
    animateStrokes(editor, [ellipseStroke(RECT, noJitter)], {});
    vi.advanceTimersByTime(10_000);
    expect(log.updated.length).toBeGreaterThan(3);
  });

  it("starts from a single point", () => {
    const { editor, log } = makeAnimEditor();
    animateStrokes(editor, [ellipseStroke(RECT, noJitter)], {});
    vi.advanceTimersByTime(1000 / DEFAULT_FPS);
    const props = log.created[0].props as { segments: unknown[] };
    expect(props.segments).toHaveLength(1);
  });

  it("marks the stroke complete only on the final frame", () => {
    const { editor, log } = makeAnimEditor();
    animateStrokes(editor, [ellipseStroke(RECT, noJitter)], {});
    vi.advanceTimersByTime(10_000);
    const completions = log.updated.map(
      (u) => (u.props as { isComplete: boolean }).isComplete,
    );
    expect(completions.filter(Boolean)).toHaveLength(1);
    expect(completions.at(-1)).toBe(true);
  });

  it("keeps every frame out of the undo stack", () => {
    // Otherwise one annotation buries the student's own history.
    const { editor, log } = makeAnimEditor();
    animateStrokes(editor, [ellipseStroke(RECT, noJitter)], {});
    vi.advanceTimersByTime(10_000);
    expect(log.historyModes.every((mode) => mode === "ignore")).toBe(true);
  });

  it("anchors the shape at the stroke's first point", () => {
    const { editor, log } = makeAnimEditor();
    const stroke = [
      { x: 40, y: 25 },
      { x: 90, y: 25 },
    ];
    animateStrokes(editor, [stroke], {});
    vi.advanceTimersByTime(10_000);
    expect(log.created[0]).toMatchObject({ x: 40, y: 25 });
  });

  it("stamps the supplied meta on each shape", () => {
    const { editor, log } = makeAnimEditor();
    animateStrokes(editor, [ellipseStroke(RECT, noJitter)], {
      meta: { owner: "ai", interactionId: "i1" },
    });
    vi.advanceTimersByTime(10_000);
    expect(log.created[0].meta).toMatchObject({ owner: "ai", interactionId: "i1" });
  });

  it("reports each shape it creates", () => {
    const { editor } = makeAnimEditor();
    const onShape = vi.fn();
    animateStrokes(editor, crossStrokes(RECT, noJitter), { onShape });
    vi.advanceTimersByTime(10_000);
    expect(onShape).toHaveBeenCalledTimes(2);
  });

  it("paces a longer stroke over more frames than a short one", () => {
    const short = makeAnimEditor();
    const long = makeAnimEditor();
    animateStrokes(short.editor, [[{ x: 0, y: 0 }, { x: 20, y: 0 }]], {});
    animateStrokes(long.editor, [[{ x: 0, y: 0 }, { x: 2000, y: 0 }]], {});
    vi.advanceTimersByTime(30_000);
    expect(long.log.updated.length).toBeGreaterThan(short.log.updated.length);
  });

  it("ignores a degenerate stroke with fewer than two points", () => {
    const { editor, log } = makeAnimEditor();
    animateStrokes(editor, [[{ x: 1, y: 1 }]], {});
    vi.advanceTimersByTime(10_000);
    expect(log.created).toHaveLength(0);
  });

  it("stops drawing when cancelled mid-stroke", () => {
    const { editor, log } = makeAnimEditor();
    const handle = animateStrokes(editor, [ellipseStroke(RECT, noJitter)], {});
    vi.advanceTimersByTime(1000 / DEFAULT_FPS * 3);
    handle.cancel();
    const after = log.updated.length;
    vi.advanceTimersByTime(10_000);
    expect(log.updated.length).toBe(after);
  });

  it("resolves done once finished", async () => {
    const { editor } = makeAnimEditor();
    const handle = animateStrokes(editor, [[{ x: 0, y: 0 }, { x: 10, y: 0 }]], {});
    vi.advanceTimersByTime(10_000);
    await expect(handle.done).resolves.toBeUndefined();
  });

  it("resolves done when cancelled, so callers never hang", async () => {
    const { editor } = makeAnimEditor();
    const handle = animateStrokes(editor, [ellipseStroke(RECT, noJitter)], {});
    handle.cancel();
    await expect(handle.done).resolves.toBeUndefined();
  });
});

describe("sequence", () => {
  it("runs steps one after another, not concurrently", async () => {
    const { editor, log } = makeAnimEditor();
    sequence([
      () => animateStrokes(editor, [[{ x: 0, y: 0 }, { x: 20, y: 0 }]], {}),
      () => animateStrokes(editor, [[{ x: 0, y: 0 }, { x: 200, y: 0 }]], {}),
    ]);
    await vi.advanceTimersByTimeAsync(50);
    expect(log.created).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(log.created).toHaveLength(2);
  });

  it("cancelling stops the remaining steps", async () => {
    const { editor, log } = makeAnimEditor();
    const handle = sequence([
      () => animateStrokes(editor, [[{ x: 0, y: 0 }, { x: 20, y: 0 }]], {}),
      () => animateStrokes(editor, [[{ x: 0, y: 0 }, { x: 200, y: 0 }]], {}),
    ]);
    await vi.advanceTimersByTimeAsync(50);
    handle.cancel();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(log.created).toHaveLength(1);
  });
});

describe("stroke geometry", () => {
  it("an ellipse closes back near where it began", () => {
    const stroke = ellipseStroke(RECT, noJitter);
    const first = stroke[0];
    const last = stroke.at(-1)!;
    expect(Math.hypot(last.x - first.x, last.y - first.y)).toBeLessThan(12);
  });

  it("a cross is two separate strokes, so the pen lifts between them", () => {
    expect(crossStrokes(RECT, noJitter)).toHaveLength(2);
  });

  it("a check is a single continuous stroke", () => {
    expect(checkStrokes(RECT, noJitter)).toHaveLength(1);
  });

  it("jitter is deterministic for the same action id", () => {
    const a = makeJitter("action_1", 2);
    const b = makeJitter("action_1", 2);
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
  });

  it("jitter differs between actions, so marks are not identical", () => {
    const a = makeJitter("action_1", 2);
    const b = makeJitter("action_2", 2);
    expect(a()).not.toBe(b());
  });

  it("jitter stays within the requested amount", () => {
    const jitter = makeJitter("seed", 1.5);
    for (let i = 0; i < 200; i++) {
      expect(Math.abs(jitter())).toBeLessThanOrEqual(1.5);
    }
  });

  it("strokeLength measures the path, not the endpoints", () => {
    expect(strokeLength([{ x: 0, y: 0 }, { x: 3, y: 4 }])).toBe(5);
  });
});
