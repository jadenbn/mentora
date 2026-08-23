/**
 * Orchestration: capture -> request -> render.
 *
 * Only the network boundary is mocked. Capture and the renderer run for real
 * against the fake editor, so this covers the seams between them.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TutorRequest, TutorResponse } from "@/types/tutor";
import { box, makeEditor } from "./fakeEditor";

const analyzeCanvasMock = vi.fn();
vi.mock("@/lib/api/api", () => ({
  analyzeCanvas: (...args: unknown[]) => analyzeCanvasMock(...args),
  TutorApiError: class extends Error {},
}));

const { EmptyCanvasError, runTutorAnalysis } = await import("@/lib/tutor/analyze");

const FRAME = box(100, 50, 800, 600);

function response(over: Partial<TutorResponse> = {}): TutorResponse {
  return {
    schema_version: "1.0",
    interaction_id: "interaction_1",
    request_id: "ea0e25c0-91c9-4fe4-a990-e82686828b35",
    status: "partial",
    confidence: 0.9,
    canvas_actions: [],
    summary: "ok",
    grounding_references: [],
    warnings: [],
    course_boundary: {
      requires_confirmation: false,
      alternatives_available: false,
    },
    learning_events: [],
    learning_delivery: { status: "disabled", event_count: 0 },
    ...over,
  };
}

function editorWithWork() {
  return makeEditor({
    shapes: [{ id: "shape:s", type: "draw", pageBounds: box(300, 200, 200, 150) }],
    pageBounds: FRAME,
  });
}

const OPTIONS = {
  mode: "hint" as const,
  userId: "user_1",
  courseId: "course_1",
  sessionId: "session_1",
  problemId: "problem_1",
  problemText: "Differentiate x^2.",
};

function sentRequest(): TutorRequest {
  return analyzeCanvasMock.mock.calls[0][0].request as TutorRequest;
}

beforeEach(() => {
  analyzeCanvasMock.mockReset();
  analyzeCanvasMock.mockResolvedValue(response());
});

describe("guard conditions", () => {
  it("refuses an empty canvas instead of sending a pointless request", async () => {
    const { editor } = makeEditor({ shapes: [] });
    await expect(runTutorAnalysis({ editor, ...OPTIONS })).rejects.toBeInstanceOf(
      EmptyCanvasError,
    );
    expect(analyzeCanvasMock).not.toHaveBeenCalled();
  });

  it("gives the empty-canvas error a message worth showing a student", async () => {
    const { editor } = makeEditor({ shapes: [] });
    const error = await runTutorAnalysis({ editor, ...OPTIONS }).catch((e) => e);
    expect(error.message).toMatch(/nothing on the canvas/i);
  });
});

describe("request assembly", () => {
  it("pins the schema version the backend expects", async () => {
    await runTutorAnalysis({ editor: editorWithWork().editor, ...OPTIONS });
    expect(sentRequest().schema_version).toBe("1.0");
  });

  it("carries the identifiers through", async () => {
    await runTutorAnalysis({ editor: editorWithWork().editor, ...OPTIONS });
    expect(sentRequest()).toMatchObject({
      user_id: "user_1",
      course_id: "course_1",
      session_id: "session_1",
      problem_id: "problem_1",
      mode: "hint",
    });
  });

  it("generates a uuid request id", async () => {
    await runTutorAnalysis({ editor: editorWithWork().editor, ...OPTIONS });
    expect(sentRequest().request_id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
    );
  });

  it("marks a button press as a manual trigger", async () => {
    await runTutorAnalysis({ editor: editorWithWork().editor, ...OPTIONS });
    expect(sentRequest().trigger).toBe("manual");
  });

  it("sends the problem text, which the backend requires to be non-empty", async () => {
    await runTutorAnalysis({ editor: editorWithWork().editor, ...OPTIONS });
    expect(sentRequest().problem.prompt_text).toBe("Differentiate x^2.");
  });

  it("includes the canvas context built from the capture", async () => {
    await runTutorAnalysis({ editor: editorWithWork().editor, ...OPTIONS });
    const canvas = sentRequest().canvas;
    expect(canvas.image_width).toBeGreaterThan(0);
    expect(canvas.shapes).toHaveLength(1);
    expect(canvas.shapes[0].owner).toBe("student");
  });

  it("attaches the captured image to the upload", async () => {
    await runTutorAnalysis({ editor: editorWithWork().editor, ...OPTIONS });
    expect(analyzeCanvasMock.mock.calls[0][0].canvasImage).toBeInstanceOf(Blob);
  });

  it.each(["mark", "hint", "explain", "stuck"] as const)(
    "forwards the %s mode",
    async (mode) => {
      await runTutorAnalysis({ editor: editorWithWork().editor, ...OPTIONS, mode });
      expect(sentRequest().mode).toBe(mode);
    },
  );
});

describe("declared client capabilities", () => {
  it("declares only the actions the renderer can actually draw", async () => {
    await runTutorAnalysis({ editor: editorWithWork().editor, ...OPTIONS });
    expect(sentRequest().client_capabilities?.supported_actions).toEqual([
      "text",
      "arrow",
      "circle",
      "underline",
      "highlight",
      "check",
      "cross",
    ]);
  });

  it("does not claim math support, since LaTeX is rendered as plain text", async () => {
    await runTutorAnalysis({ editor: editorWithWork().editor, ...OPTIONS });
    const caps = sentRequest().client_capabilities!;
    expect(caps.supported_actions).not.toContain("math");
    expect(caps.supports_latex).toBe(false);
  });

  it("does not claim selection-crop support until it is built", async () => {
    await runTutorAnalysis({ editor: editorWithWork().editor, ...OPTIONS });
    expect(sentRequest().client_capabilities?.supports_selection_crop).toBe(false);
  });
});

describe("rendering the reply", () => {
  it("returns the tutor response to the caller", async () => {
    const expected = response({ summary: "a hint" });
    analyzeCanvasMock.mockResolvedValue(expected);
    const result = await runTutorAnalysis({
      editor: editorWithWork().editor,
      ...OPTIONS,
    });
    expect(result).toBe(expected);
  });

  it("draws returned actions using the same frame the image was captured in", async () => {
    analyzeCanvasMock.mockResolvedValue(
      response({
        canvas_actions: [
          { action_id: "a1", type: "text", position: { x: 0.5, y: 0.5 }, text: "hi" },
        ],
      }),
    );
    const fake = editorWithWork();
    await runTutorAnalysis({ editor: fake.editor, ...OPTIONS });
    expect(fake.created[0]).toMatchObject({ x: 500, y: 350 });
  });

  it("tags drawn shapes with the interaction id from the response", async () => {
    analyzeCanvasMock.mockResolvedValue(
      response({
        interaction_id: "interaction_xyz",
        canvas_actions: [
          { action_id: "a1", type: "text", position: { x: 0, y: 0 }, text: "hi" },
        ],
      }),
    );
    const fake = editorWithWork();
    await runTutorAnalysis({ editor: fake.editor, ...OPTIONS });
    expect(fake.created[0].meta).toMatchObject({
      interactionId: "interaction_xyz",
    });
  });

  it("draws nothing when the tutor returns no actions", async () => {
    const fake = editorWithWork();
    await runTutorAnalysis({ editor: fake.editor, ...OPTIONS });
    expect(fake.created).toHaveLength(0);
  });

  it("propagates a network failure instead of silently drawing nothing", async () => {
    analyzeCanvasMock.mockRejectedValue(new Error("boom"));
    const fake = editorWithWork();
    await expect(
      runTutorAnalysis({ editor: fake.editor, ...OPTIONS }),
    ).rejects.toThrow("boom");
    expect(fake.created).toHaveLength(0);
  });
});
