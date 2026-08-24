import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Box, Editor } from "tldraw";
import {
  DEMO_META_FLAG,
  clearDemoShapes,
  runDemoScript,
} from "@/lib/annotations/demoScript";

const FRAME = { x: 0, y: 0, w: 1000, h: 800 } as Box;

interface Shape {
  id: string;
  type: string;
  meta?: Record<string, unknown>;
  props?: Record<string, unknown>;
}

function makeScriptEditor(seed: Shape[] = []) {
  const shapes = new Map(seed.map((s) => [s.id, s]));
  const deleted: string[] = [];

  const editor = {
    run: (fn: () => void) => fn(),
    getCurrentPageShapeIds: () => new Set(shapes.keys()),
    getShape: (id: string) => shapes.get(id),
    deleteShapes: (ids: string[]) => {
      for (const id of ids) {
        deleted.push(id);
        shapes.delete(id);
      }
    },
    createShape: (partial: Shape) => shapes.set(partial.id, partial),
    updateShape: (partial: Shape) => {
      const existing = shapes.get(partial.id);
      if (existing) {
        shapes.set(partial.id, { ...existing, ...partial });
      }
    },
    getViewportPageBounds: () => FRAME,
  } as unknown as Editor;

  return { editor, shapes, deleted };
}

/** Run the whole script to completion under fake timers. */
async function runToEnd(editor: Editor, onPhase?: (p: string) => void) {
  const handle = runDemoScript(editor, FRAME, { onPhase });
  await vi.advanceTimersByTimeAsync(120_000);
  await handle.done;
  return handle;
}

function textOf(shape: Shape): string {
  return JSON.stringify(shape.props ?? {});
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("clearDemoShapes", () => {
  it("removes shapes the script created", () => {
    const { editor, deleted } = makeScriptEditor([
      { id: "a", type: "text", meta: { [DEMO_META_FLAG]: true } },
    ]);
    clearDemoShapes(editor);
    expect(deleted).toEqual(["a"]);
  });

  it("leaves the student's own work alone", () => {
    const { editor, deleted } = makeScriptEditor([
      { id: "mine", type: "draw" },
      { id: "demo", type: "text", meta: { [DEMO_META_FLAG]: true } },
    ]);
    clearDemoShapes(editor);
    expect(deleted).toEqual(["demo"]);
  });

  it("leaves real tutor annotations alone", () => {
    const { editor, deleted } = makeScriptEditor([
      { id: "ai", type: "text", meta: { owner: "ai", interactionId: "i1" } },
    ]);
    clearDemoShapes(editor);
    expect(deleted).toEqual([]);
  });
});

describe("runDemoScript", () => {
  it("draws the whole session", async () => {
    const { editor, shapes } = makeScriptEditor();
    await runToEnd(editor);
    expect(shapes.size).toBeGreaterThan(10);
  });

  it("uses all three ownership kinds", async () => {
    const { editor, shapes } = makeScriptEditor();
    await runToEnd(editor);
    const owners = new Set(
      [...shapes.values()].map((s) => s.meta?.owner as string),
    );
    expect(owners).toEqual(new Set(["system", "student", "ai"]));
  });

  it("flags everything it creates so a rerun can clean up", async () => {
    const { editor, shapes } = makeScriptEditor();
    await runToEnd(editor);
    expect(
      [...shapes.values()].every((s) => s.meta?.[DEMO_META_FLAG] === true),
    ).toBe(true);
  });

  it("poses the problem as system-owned content", async () => {
    const { editor, shapes } = makeScriptEditor();
    await runToEnd(editor);
    const system = [...shapes.values()].filter(
      (s) => s.meta?.owner === "system",
    );
    expect(system).toHaveLength(1);
    expect(textOf(system[0])).toContain("dz/dt");
  });

  it("writes the wrong answer and then the corrected one", async () => {
    const { editor, shapes } = makeScriptEditor();
    await runToEnd(editor);
    const student = [...shapes.values()]
      .filter((s) => s.meta?.owner === "student")
      .map(textOf)
      .join(" ");
    expect(student).toContain("8t^8");
    expect(student).toContain("8t^7");
  });

  it("marks the error before the student corrects it", async () => {
    const phases: string[] = [];
    const { editor } = makeScriptEditor();
    await runToEnd(editor, (p) => phases.push(p));
    expect(phases.indexOf("Mark")).toBeLessThan(phases.indexOf("Student corrects"));
  });

  it("reports the beats in narrative order", async () => {
    const phases: string[] = [];
    const { editor } = makeScriptEditor();
    await runToEnd(editor, (p) => phases.push(p));
    expect(phases).toEqual([
      "Problem",
      "Student working",
      "Mark",
      "Hint",
      "Explain",
      "Student corrects",
      "Mark",
      "Done",
    ]);
  });

  it("ends with the tutor confirming", async () => {
    const { editor, shapes } = makeScriptEditor();
    await runToEnd(editor);
    const ai = [...shapes.values()]
      .filter((s) => s.meta?.owner === "ai")
      .map(textOf)
      .join(" ");
    expect(ai).toContain("nice recovery");
  });

  it("clears a previous run instead of stacking on top of it", async () => {
    const { editor, shapes } = makeScriptEditor();
    await runToEnd(editor);
    const first = shapes.size;
    await runToEnd(editor);
    expect(shapes.size).toBe(first);
  });

  it("stops partway when cancelled", async () => {
    const { editor, shapes } = makeScriptEditor();
    const handle = runDemoScript(editor, FRAME, {});
    await vi.advanceTimersByTimeAsync(500);
    handle.cancel();
    const partial = shapes.size;
    await vi.advanceTimersByTimeAsync(120_000);
    expect(shapes.size).toBe(partial);
  });
});
