/**
 * One tutor interaction, end to end.
 *
 * capture the student's work -> ask the backend -> draw the answer.
 * Only the network is faked; capture and rendering run for real.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EmptyCanvasError, runTutorAnalysis } from "@/lib/tutor/analyze";
import { AI_SHAPE_OWNER } from "@/lib/annotations/renderCanvasActions";
import { box, makeEditor } from "./fakeEditor";

const RESPONSE = {
  interaction_id: "interaction_7",
  status: "partial",
  summary: "You dropped the coefficient.",
  canvas_actions: [
    { type: "text", position: { x: 0.5, y: 0.5 }, text: "What about the 2?" },
    { type: "circle", target: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 } },
  ],
};

const student = (id: string, bounds = box(150, 300, 100, 200)) => ({
  id,
  type: "draw",
  meta: { owner: "student" },
  pageBounds: bounds,
});

const priorMark = (id: string) => ({
  id,
  type: "text",
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

  it("tells the backend where its earlier marks are", async () => {
    const fake = makeEditor({ shapes: [student("s1"), priorMark("ai1")] });
    const spy = mockFetch();
    await run(fake.editor);
    const body = spy.mock.calls[0][1].body as FormData;
    expect(JSON.parse(body.get("prior_annotations") as string)).toHaveLength(1);
  });

  it("sends the structured problem separately from the image", async () => {
    const fake = makeEditor({ shapes: [student("s1")] });
    const spy = mockFetch();
    await run(fake.editor, {
      problem: {
        id: "problem_1",
        courseId: "course_demo",
        documentId: "doc_1",
        source: "generated",
        prompt: "Differentiate x².",
      },
    });
    const body = spy.mock.calls[0][1].body as FormData;
    expect(JSON.parse(body.get("problem_context") as string)).toMatchObject({
      id: "problem_1",
      prompt: "Differentiate x².",
    });
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
