/**
 * One tutor interaction, end to end.
 *
 * capture the student's work -> ask the backend -> draw the answer.
 * Only the network is faked; capture and rendering run for real.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EmptyCanvasError, runTutorAnalysis } from "@/lib/tutor/analyze";
import { AI_SHAPE_OWNER } from "@/lib/annotations/renderCanvasActions";
import type { RenderContext } from "@/lib/annotations/renderCanvasActions";
import type { ProblemContext } from "@/types/domain";
import type { TutorResponse } from "@/types/tutor";
import { box, makeEditor } from "./fakeEditor";

const RESPONSE = {
  interaction_id: "interaction_7",
  status: "partial",
  summary: "You dropped the coefficient.",
  canvas_actions: [
    { type: "highlight", target: { x: 0.5, y: 0.5, width: 0.1, height: 0.1 } },
    { type: "circle", target: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 } },
  ],
};

const PROBLEM: ProblemContext = {
  id: "problem_1",
  course_id: "course_demo",
  document_id: "document_1",
  source: "generated",
  prompt: "Find the derivative of $f(x)=e^{3x}$.",
};

const student = (id: string, bounds = box(150, 300, 100, 200)) => ({
  id,
  type: "draw",
  meta: { owner: "student" },
  pageBounds: bounds,
});

const priorMark = (id: string) => ({
  id,
  type: "geo",
  meta: { owner: AI_SHAPE_OWNER, interactionId: "interaction_1" },
  pageBounds: box(200, 400, 100, 100),
});

function mockFetch(body: unknown = RESPONSE, ok = true, status = 200) {
  const spy = vi.fn(
    async (_url: string, _init: RequestInit) =>
      ({ ok, status, json: async () => body }) as Response,
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}

const run = (editor: ReturnType<typeof makeEditor>["editor"], over = {}) =>
  runTutorAnalysis({ editor, mode: "hint", courseId: "course_demo", ...over });

beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
afterEach(() => vi.unstubAllGlobals());

describe("the happy path", () => {
  it("draws the tutor's answer onto the canvas", async () => {
    const fake = makeEditor({ shapes: [student("s1")] });
    mockFetch();
    await run(fake.editor);
    expect(fake.created).toHaveLength(2);
  });

  it("returns the tutor's verdict to the caller", async () => {
    const fake = makeEditor({ shapes: [student("s1")] });
    mockFetch();
    const response = await run(fake.editor);
    expect(response).toMatchObject({ status: "partial", summary: "You dropped the coefficient." });
  });

  it("tags what it drew with the interaction the backend reported", async () => {
    const fake = makeEditor({ shapes: [student("s1")] });
    mockFetch();
    await run(fake.editor);
    expect(fake.created[0].meta).toMatchObject({ interactionId: "interaction_7" });
  });

  it("captures the canvas before tutor marks are rendered", async () => {
    const fake = makeEditor({
      shapes: [
        student("s1"),
        { ...student("highlight"), type: "draw" },
      ],
    });
    mockFetch();
    let snapshot: unknown;
    await run(fake.editor, {
      onResponse: (_response: TutorResponse, _context: RenderContext, captured: unknown) => {
        snapshot = captured;
      },
    });
    expect(snapshot).toEqual({ shapes: ["s1", "highlight"] });
  });
});

describe("what it sends", () => {
  it("sends the requested mode and course", async () => {
    const fake = makeEditor({ shapes: [student("s1")] });
    const spy = mockFetch();
    await run(fake.editor, { mode: "mark", courseId: "course_linear" });
    const body = spy.mock.calls[0][1].body as FormData;
    expect(body.get("mode")).toBe("mark");
    expect(body.get("course_id")).toBe("course_linear");
  });

  it("carries a reviewed question alongside the canvas", async () => {
    const fake = makeEditor({ shapes: [student("s1")] });
    const spy = mockFetch();
    await run(fake.editor, {
      mode: "explain",
      studentQuestion: "why can't I cancel the x?",
    });
    const body = spy.mock.calls[0][1].body as FormData;
    expect(body.get("transcript")).toBe("why can't I cancel the x?");
    expect(body.get("canvas_image")).not.toBeNull();
  });

  it("sends no question when the student used a button", async () => {
    const fake = makeEditor({ shapes: [student("s1")] });
    const spy = mockFetch();
    await run(fake.editor);
    const body = spy.mock.calls[0][1].body as FormData;
    expect(body.has("transcript")).toBe(false);
  });

  it("tells the backend where its earlier marks are", async () => {
    const fake = makeEditor({ shapes: [student("s1"), priorMark("ai1")] });
    const spy = mockFetch();
    await run(fake.editor);
    const body = spy.mock.calls[0][1].body as FormData;
    expect(JSON.parse(body.get("prior_annotations") as string)).toHaveLength(1);
  });

  it.each(["mark", "hint", "explain", "stuck"] as const)(
    "includes the current eligible selection for %s",
    async (mode) => {
      const fake = makeEditor({
        shapes: [student("s1"), student("s2", box(400, 500, 80, 60))],
        selectedIds: ["s2"],
      });
      const spy = mockFetch();

      await run(fake.editor, { mode });

      const body = spy.mock.calls[0][1].body as FormData;
      expect(JSON.parse(body.get("selection_bounds") as string)).toEqual({
        x: expect.any(Number),
        y: expect.any(Number),
        width: expect.any(Number),
        height: expect.any(Number),
      });
    },
  );

  it("omits selection metadata for a full-board request", async () => {
    const fake = makeEditor({ shapes: [student("s1")] });
    const spy = mockFetch();
    await run(fake.editor);
    expect((spy.mock.calls[0][1].body as FormData).has("selection_bounds")).toBe(false);
  });

  it("ignores selected tutor marks when deciding the focus", async () => {
    const fake = makeEditor({
      shapes: [student("s1"), priorMark("ai1")],
      selectedIds: ["ai1"],
    });
    const spy = mockFetch();
    await run(fake.editor);
    expect((spy.mock.calls[0][1].body as FormData).has("selection_bounds")).toBe(false);
  });
});

describe("when there is nothing to analyze", () => {
  it("refuses an empty canvas without calling the backend", async () => {
    const fake = makeEditor({ shapes: [] });
    const spy = mockFetch();
    await expect(run(fake.editor)).rejects.toBeInstanceOf(EmptyCanvasError);
    expect(spy).not.toHaveBeenCalled();
  });

  it("refuses a canvas holding only earlier feedback", async () => {
    const fake = makeEditor({ shapes: [priorMark("ai1")] });
    const spy = mockFetch();
    await expect(run(fake.editor)).rejects.toBeInstanceOf(EmptyCanvasError);
    expect(spy).not.toHaveBeenCalled();
  });

  it.each(["mark", "hint", "explain", "stuck"] as const)(
    "lets a student use %s against the problem before drawing",
    async (mode) => {
      const fake = makeEditor({ shapes: [] });
      const spy = mockFetch();
      await run(fake.editor, { mode, problem: PROBLEM });
      const body = spy.mock.calls[0][1].body as FormData;
      expect(body.get("canvas_image")).toBeNull();
      expect(body.has("prior_annotations")).toBe(false);
      expect(body.has("selection_bounds")).toBe(false);
      expect(JSON.parse(body.get("problem_context") as string)).toEqual(PROBLEM);
    },
  );

  it("lets that student ask a typed or spoken question too", async () => {
    const fake = makeEditor({ shapes: [] });
    const spy = mockFetch();
    await run(fake.editor, {
      mode: "stuck",
      problem: PROBLEM,
      studentQuestion: "what is this even asking?",
    });
    const body = spy.mock.calls[0][1].body as FormData;
    expect(body.get("transcript")).toBe("what is this even asking?");
  });

  it("drops spatial actions from an image-less response", async () => {
    const fake = makeEditor({ shapes: [] });
    mockFetch();
    const response = await run(fake.editor, { mode: "hint", problem: PROBLEM });
    expect(response.canvas_actions).toEqual([]);
    expect(fake.created).toEqual([]);
  });

  it("does not hide a student export failure behind the problem-only path", async () => {
    const fake = makeEditor({ shapes: [student("s1")], image: null });
    const spy = mockFetch();
    await expect(run(fake.editor, { mode: "stuck", problem: PROBLEM })).rejects.toBeInstanceOf(
      EmptyCanvasError,
    );
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("when the backend fails", () => {
  it("propagates the error and leaves the canvas alone", async () => {
    const fake = makeEditor({ shapes: [student("s1")] });
    mockFetch({ detail: null }, false, 502);
    await expect(run(fake.editor)).rejects.toThrow();
    expect(fake.created).toHaveLength(0);
    expect(fake.deleted).toHaveLength(0);
  });
});
