import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Editor } from "tldraw";
import { animateCanvasActions } from "@/lib/annotations/animateActions";

function makeEditor() {
  const shapes = new Map<string, Record<string, unknown>>();
  const created: Record<string, unknown>[] = [];
  const updated: Record<string, unknown>[] = [];
  const editor = {
    run: (fn: () => void) => fn(),
    getCurrentPageShapeIds: () => new Set(shapes.keys()),
    getShape: (id: string) => shapes.get(id),
    deleteShapes: (ids: string[]) => ids.forEach((id) => shapes.delete(id)),
    createShape: (shape: Record<string, unknown>) => {
      shapes.set(shape.id as string, shape);
      created.push(shape);
    },
    updateShape: (shape: Record<string, unknown>) => {
      const current = shapes.get(shape.id as string);
      if (current) {
        Object.assign(current, shape);
      }
      updated.push(shape);
    },
  } as unknown as Editor;

  return { editor, created, updated };
}

const CONTEXT = {
  bounds: { x: 100, y: 200, w: 400, h: 800 },
  interactionId: "interaction_1",
};

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("animateCanvasActions", () => {
  it("creates a highlight region immediately", async () => {
    const fake = makeEditor();
    const handle = animateCanvasActions(
      fake.editor,
      [{ type: "highlight", target: { x: 0.25, y: 0.5, width: 0.2, height: 0.1 } }],
      CONTEXT,
    );

    await vi.advanceTimersByTimeAsync(1);
    expect(fake.created).toHaveLength(1);
    expect(fake.created[0]).toMatchObject({ type: "geo", meta: { owner: "ai" }, props: { fill: "semi" } });
    await handle.done;
  });

  it("draws geometric feedback as progressive freehand strokes", async () => {
    const fake = makeEditor();
    const handle = animateCanvasActions(
      fake.editor,
      [{ type: "circle", target: { x: 0.1, y: 0.2, width: 0.3, height: 0.2 } }],
      CONTEXT,
    );

    await vi.advanceTimersByTimeAsync(5_000);
    await handle.done;
    expect(fake.created).toHaveLength(1);
    expect(fake.created[0]).toMatchObject({ type: "draw", meta: { owner: "ai" } });
    expect(fake.updated.length).toBeGreaterThan(3);
  });

  it("cancels an in-flight reveal without leaving later actions running", async () => {
    const fake = makeEditor();
    const handle = animateCanvasActions(
      fake.editor,
      [
        { type: "circle", target: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 } },
        { type: "check", target: { x: 0.2, y: 0.2, width: 0.2, height: 0.2 } },
      ],
      CONTEXT,
    );

    await vi.advanceTimersByTimeAsync(100);
    handle.cancel();
    const created = fake.created.length;
    await vi.advanceTimersByTimeAsync(5_000);
    await handle.done;
    expect(fake.created.length).toBe(created);
  });
});
