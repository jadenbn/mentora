import { describe, expect, it } from "vitest";
import {
  AI_SHAPE_OWNER,
  clearAiShapes,
  renderCanvasActions,
} from "@/lib/annotations/renderCanvasActions";
import type { CanvasAction } from "@/types/tutor";
import { box, makeEditor } from "./fakeEditor";

// 800x600 of world space starting at (100,50): a normalized 0.5 lands at 500/350.
const FRAME = box(100, 50, 800, 600);
const CTX = { bounds: FRAME, interactionId: "interaction_1" };

function render(actions: CanvasAction[], editorOptions = {}) {
  const fake = makeEditor(editorOptions);
  renderCanvasActions(fake.editor, actions, CTX);
  return fake;
}

const textAction = (over: Partial<CanvasAction> = {}) =>
  ({
    action_id: "a1",
    type: "text",
    position: { x: 0.5, y: 0.5 },
    text: "check this sign",
    ...over,
  }) as CanvasAction;

describe("coordinate conversion", () => {
  it("places a point action at the matching world position", () => {
    const { created } = render([textAction()]);
    expect(created[0]).toMatchObject({ x: 500, y: 350 });
  });

  it("maps the normalized origin to the frame origin", () => {
    const { created } = render([textAction({ position: { x: 0, y: 0 } } as never)]);
    expect(created[0]).toMatchObject({ x: 100, y: 50 });
  });

  it("maps the far corner to the frame's far corner", () => {
    const { created } = render([textAction({ position: { x: 1, y: 1 } } as never)]);
    expect(created[0]).toMatchObject({ x: 900, y: 650 });
  });

  it("converts a target rectangle into world size", () => {
    const { created } = render([
      {
        action_id: "a1",
        type: "circle",
        target: { x: 0.25, y: 0.25, width: 0.25, height: 0.25 },
      } as CanvasAction,
    ]);
    expect(created[0]).toMatchObject({ x: 300, y: 200 });
    expect(created[0].props).toMatchObject({ w: 200, h: 150 });
  });

  it("never produces a zero-sized shape from a vanishingly small target", () => {
    const { created } = render([
      {
        action_id: "a1",
        type: "circle",
        target: { x: 0.5, y: 0.5, width: 0.0000001, height: 0.0000001 },
      } as CanvasAction,
    ]);
    expect((created[0].props as { w: number }).w).toBeGreaterThanOrEqual(1);
  });
});

describe("action types", () => {
  it("renders text as a text shape carrying the tutor's words", () => {
    const { created } = render([textAction()]);
    expect(created[0].type).toBe("text");
    expect(created[0].props).toHaveProperty("richText");
  });

  it("renders math as text, since there is no LaTeX renderer yet", () => {
    const { created } = render([
      { action_id: "a1", type: "math", position: { x: 0.5, y: 0.5 }, latex: "x^2" } as CanvasAction,
    ]);
    expect(created[0].type).toBe("text");
  });

  it("anchors an arrow at its start and offsets the end relatively", () => {
    const { created } = render([
      {
        action_id: "a1",
        type: "arrow",
        start: { x: 0.25, y: 0.25 },
        end: { x: 0.5, y: 0.5 },
      } as CanvasAction,
    ]);
    expect(created[0]).toMatchObject({ type: "arrow", x: 300, y: 200 });
    expect(created[0].props).toMatchObject({
      start: { x: 0, y: 0 },
      end: { x: 200, y: 150 },
    });
  });

  it("gives an arrow a head at the end only", () => {
    const { created } = render([
      {
        action_id: "a1",
        type: "arrow",
        start: { x: 0, y: 0 },
        end: { x: 1, y: 1 },
      } as CanvasAction,
    ]);
    expect(created[0].props).toMatchObject({
      arrowheadStart: "none",
      arrowheadEnd: "arrow",
    });
  });

  it("draws a circle as an unfilled ellipse", () => {
    const { created } = render([
      { action_id: "a1", type: "circle", target: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 } } as CanvasAction,
    ]);
    expect(created[0].props).toMatchObject({ geo: "ellipse", fill: "none" });
  });

  it("draws a highlight as a translucent rectangle", () => {
    const { created } = render([
      { action_id: "a1", type: "highlight", target: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 } } as CanvasAction,
    ]);
    expect(created[0].props).toMatchObject({
      geo: "rectangle",
      fill: "semi",
      color: "yellow",
    });
  });

  it("draws an underline as a headless rule along the bottom edge", () => {
    const { created } = render([
      { action_id: "a1", type: "underline", target: { x: 0.25, y: 0.25, width: 0.25, height: 0.25 } } as CanvasAction,
    ]);
    // target bottom edge: y = 50 + (0.25+0.25)*600 = 350
    expect(created[0]).toMatchObject({ type: "arrow", x: 300, y: 350 });
    expect(created[0].props).toMatchObject({
      arrowheadStart: "none",
      arrowheadEnd: "none",
      end: { x: 200, y: 0 },
    });
  });

  it("marks a check in green and a cross in red", () => {
    const target = { x: 0.1, y: 0.1, width: 0.2, height: 0.2 };
    const { created } = render([
      { action_id: "a1", type: "check", target } as CanvasAction,
      { action_id: "a2", type: "cross", target } as CanvasAction,
    ]);
    expect(created[0].props).toMatchObject({ color: "green" });
    expect(created[1].props).toMatchObject({ color: "red" });
  });

  it("places a mark just past the target's top-right corner", () => {
    const { created } = render([
      { action_id: "a1", type: "check", target: { x: 0.25, y: 0.25, width: 0.25, height: 0.25 } } as CanvasAction,
    ]);
    expect(created[0]).toMatchObject({ x: 500, y: 200 });
  });

  it("attaches an optional label to a target action", () => {
    const { created } = render([
      {
        action_id: "a1",
        type: "circle",
        target: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 },
        label: "look here",
      } as CanvasAction,
    ]);
    expect(created[0].props).toHaveProperty("richText");
  });

  it("omits richText entirely when no label is supplied", () => {
    const { created } = render([
      { action_id: "a1", type: "circle", target: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 } } as CanvasAction,
    ]);
    expect(created[0].props).not.toHaveProperty("richText");
  });

  it("skips an unrecognised action from a newer backend instead of throwing", () => {
    const { created } = render([
      { action_id: "a1", type: "hologram", position: { x: 0.5, y: 0.5 } } as unknown as CanvasAction,
      textAction({ action_id: "a2" }),
    ]);
    expect(created).toHaveLength(1);
    expect(created[0].meta).toMatchObject({ actionId: "a2" });
  });
});

describe("ownership and provenance", () => {
  it("stamps every shape as AI-owned", () => {
    const { created } = render([textAction()]);
    expect(created[0].meta).toMatchObject({ owner: AI_SHAPE_OWNER });
  });

  it("records the interaction and action ids for traceability", () => {
    const { created } = render([textAction()]);
    expect(created[0].meta).toMatchObject({
      interactionId: "interaction_1",
      actionId: "a1",
    });
  });

  it("gives each shape a distinct id", () => {
    const { created } = render([textAction(), textAction({ action_id: "a2" })]);
    expect(created[0].id).not.toBe(created[1].id);
  });
});

describe("idempotency and clearing", () => {
  it("creates nothing when there are no actions", () => {
    const { created } = render([]);
    expect(created).toHaveLength(0);
  });

  it("replaces its own shapes when the same interaction renders twice", () => {
    const fake = makeEditor({
      shapes: [
        {
          id: "shape:old",
          type: "text",
          meta: { owner: "ai", interactionId: "interaction_1", actionId: "a1" },
        },
      ],
    });
    renderCanvasActions(fake.editor, [textAction()], CTX);
    expect(fake.deleted).toContain("shape:old");
  });

  it("leaves shapes from a different interaction alone", () => {
    const fake = makeEditor({
      shapes: [
        {
          id: "shape:other",
          type: "text",
          meta: { owner: "ai", interactionId: "interaction_0", actionId: "z" },
        },
      ],
    });
    renderCanvasActions(fake.editor, [textAction()], CTX);
    expect(fake.deleted).not.toContain("shape:other");
  });

  it("never deletes student work", () => {
    const fake = makeEditor({
      shapes: [
        { id: "shape:student", type: "draw" },
        {
          id: "shape:ai",
          type: "text",
          meta: { owner: "ai", interactionId: "interaction_1", actionId: "a1" },
        },
      ],
    });
    renderCanvasActions(fake.editor, [textAction()], CTX);
    expect(fake.deleted).toEqual(["shape:ai"]);
  });

  it("clearAiShapes removes every AI shape regardless of interaction", () => {
    const fake = makeEditor({
      shapes: [
        { id: "shape:ai1", type: "text", meta: { owner: "ai", interactionId: "i1" } },
        { id: "shape:ai2", type: "geo", meta: { owner: "ai", interactionId: "i2" } },
        { id: "shape:student", type: "draw" },
        { id: "shape:system", type: "text", meta: { owner: "system" } },
      ],
    });
    clearAiShapes(fake.editor);
    expect(fake.deleted.sort()).toEqual(["shape:ai1", "shape:ai2"]);
  });

  it("clearAiShapes is a no-op on a canvas with no AI shapes", () => {
    const fake = makeEditor({ shapes: [{ id: "shape:s", type: "draw" }] });
    clearAiShapes(fake.editor);
    expect(fake.deleted).toHaveLength(0);
  });
});
