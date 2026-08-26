/**
 * The annotation renderer.
 *
 * This is the only place normalized image coordinates become tldraw world
 * coordinates. The frame below is deliberately offset from the origin so a
 * missing translation fails loudly.
 */

import { describe, expect, it } from "vitest";
import {
  AI_SHAPE_OWNER,
  clearAiShapes,
  hasAiShapes,
  renderCanvasActions,
} from "@/lib/annotations/renderCanvasActions";
import type { CanvasAction } from "@/types/tutor";
import { box, makeEditor } from "./fakeEditor";

const FRAME = box(100, 200, 400, 800);
const CONTEXT = { bounds: FRAME, interactionId: "interaction_1" };

const render = (actions: CanvasAction[], context = CONTEXT) => {
  const fake = makeEditor({ shapes: [] });
  renderCanvasActions(fake.editor, actions, context);
  return fake;
};

const highlight = (over = {}): CanvasAction =>
  ({ type: "highlight", target: { x: 0.25, y: 0.5, width: 0.2, height: 0.1 }, ...over }) as CanvasAction;

const circle = (over = {}): CanvasAction =>
  ({ type: "circle", target: { x: 0.25, y: 0.25, width: 0.5, height: 0.5 }, ...over }) as CanvasAction;

const mark = (type: "check" | "cross"): CanvasAction =>
  ({ type, target: { x: 0.25, y: 0.25, width: 0.5, height: 0.5 } }) as CanvasAction;

describe("coordinate conversion", () => {
  it("places a highlight at the world rectangle its normalized target names", () => {
    const { created } = render([highlight()]);
    expect(created[0]).toMatchObject({ x: 200, y: 600 });
    expect(created[0].props).toMatchObject({ w: 80, h: 80 });
  });

  it("sizes a circle to the world rectangle its target names", () => {
    const { created } = render([circle()]);
    expect(created[0]).toMatchObject({ x: 200, y: 400 });
    expect(created[0].props).toMatchObject({ w: 200, h: 400 });
  });

  it("places a mark against its target rather than the page origin", () => {
    const { created } = render([mark("check")]);
    expect(created[0].x).toBeGreaterThanOrEqual(200);
    expect(created[0].y).toBeGreaterThanOrEqual(400);
  });
});

describe("action coverage", () => {
  it("renders a highlight", () => {
    expect(render([highlight()]).created).toHaveLength(1);
  });

  it("renders a circle as an outline, not a filled blob over the work", () => {
    const { created } = render([circle()]);
    expect(created[0].props).toMatchObject({ geo: "ellipse", fill: "none" });
  });

  it("renders a check and a cross as visually opposite marks", () => {
    const check = render([mark("check")]).created[0];
    const cross = render([mark("cross")]).created[0];
    expect(check.props).not.toEqual(cross.props);
  });

  it("renders every action it is given", () => {
    const { created } = render([highlight(), circle(), mark("check"), mark("cross")]);
    expect(created).toHaveLength(4);
  });

  it("skips an action type it does not know rather than throwing", () => {
    // A newer backend must degrade gracefully, not white-screen the canvas.
    const { created } = render([{ type: "hologram" } as unknown as CanvasAction]);
    expect(created).toHaveLength(0);
  });

  it("renders nothing for an empty plan without touching the canvas", () => {
    const { created, deleted } = render([]);
    expect(created).toHaveLength(0);
    expect(deleted).toHaveLength(0);
  });
});

describe("provenance", () => {
  it("tags every shape it creates as tutor-authored", () => {
    const { created } = render([highlight(), circle(), mark("check")]);
    for (const shape of created) {
      expect(shape.meta).toMatchObject({ owner: AI_SHAPE_OWNER });
    }
  });

  it("records which interaction produced each shape", () => {
    const { created } = render([highlight()]);
    expect(created[0].meta).toMatchObject({ interactionId: "interaction_1" });
  });
});

describe("replacing earlier feedback", () => {
  it("replaces its own shapes when the same interaction renders again", () => {
    const fake = makeEditor({
      shapes: [{ id: "old", type: "geo", meta: { owner: AI_SHAPE_OWNER, interactionId: "interaction_1" } }],
    });
    renderCanvasActions(fake.editor, [highlight()], CONTEXT);
    expect(fake.deleted).toEqual(["old"]);
  });

  it("leaves feedback from a different interaction in place", () => {
    // Follow-up tutoring builds on earlier marks; a new interaction must not
    // wipe the conversation it is continuing.
    const fake = makeEditor({
      shapes: [{ id: "earlier", type: "geo", meta: { owner: AI_SHAPE_OWNER, interactionId: "interaction_0" } }],
    });
    renderCanvasActions(fake.editor, [highlight()], CONTEXT);
    expect(fake.deleted).toEqual([]);
  });

  it("never deletes the student's work", () => {
    const fake = makeEditor({
      shapes: [{ id: "student", type: "draw", meta: { owner: "student" } }],
    });
    renderCanvasActions(fake.editor, [highlight()], CONTEXT);
    expect(fake.deleted).toEqual([]);
  });
});

describe("clearAiShapes", () => {
  it("reports whether tutor feedback is present", () => {
    const fake = makeEditor({
      shapes: [{ id: "ai", type: "geo", meta: { owner: AI_SHAPE_OWNER } }],
    });
    expect(hasAiShapes(fake.editor)).toBe(true);
    expect(hasAiShapes(makeEditor({ shapes: [] }).editor)).toBe(false);
  });

  it("removes tutor feedback from every interaction", () => {
    const fake = makeEditor({
      shapes: [
        { id: "a", type: "geo", meta: { owner: AI_SHAPE_OWNER, interactionId: "i0" } },
        { id: "b", type: "geo", meta: { owner: AI_SHAPE_OWNER, interactionId: "i1" } },
      ],
    });
    clearAiShapes(fake.editor);
    expect(fake.deleted.sort()).toEqual(["a", "b"]);
  });

  it("leaves the student's work untouched", () => {
    const fake = makeEditor({
      shapes: [
        { id: "student", type: "draw", meta: { owner: "student" } },
        { id: "ai", type: "geo", meta: { owner: AI_SHAPE_OWNER } },
      ],
    });
    clearAiShapes(fake.editor);
    expect(fake.deleted).toEqual(["ai"]);
  });

  it("is safe on a canvas with no feedback on it", () => {
    const fake = makeEditor({ shapes: [{ id: "s", type: "draw", meta: { owner: "student" } }] });
    expect(() => clearAiShapes(fake.editor)).not.toThrow();
    expect(fake.deleted).toEqual([]);
  });
});
