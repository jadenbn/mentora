import { describe, expect, it } from "vitest";
import { ensureProblemShape, problemShapeId, PROBLEM_SHAPE_TYPE } from "@/lib/problems/renderProblem";
import { SYSTEM_SHAPE_OWNER } from "@/lib/canvas/ownership";
import { box, makeEditor } from "./fakeEditor";

const problem = {
  id: "problem_1",
  course_id: "course_1",
  document_id: "doc_1",
  source: "generated" as const,
  prompt: "Solve $x=1$.",
};

describe("ensureProblemShape", () => {
  it("creates one locked system-owned shape near the viewport", () => {
    const { editor, created } = makeEditor({ viewport: box(100, 200, 400, 300) });
    expect(ensureProblemShape(editor, problem)).toBe(true);
    expect(created[0]).toMatchObject({
      id: problemShapeId(problem.id),
      type: PROBLEM_SHAPE_TYPE,
      x: 180,
      y: 280,
      isLocked: true,
      meta: { owner: SYSTEM_SHAPE_OWNER, problemId: problem.id },
      props: { problemId: problem.id, w: 680, h: 180 },
    });
  });

  it("is idempotent after the shape is restored", () => {
    const first = makeEditor();
    ensureProblemShape(first.editor, problem);
    const second = makeEditor({
      shapes: [{ id: problemShapeId(problem.id), type: PROBLEM_SHAPE_TYPE }],
    });
    expect(ensureProblemShape(second.editor, problem)).toBe(false);
    expect(second.created).toHaveLength(0);
  });

  it("replaces a legacy problem note without removing other system shapes", () => {
    const legacy = {
      id: "legacy",
      type: "note",
      x: 240,
      y: 260,
      meta: { owner: SYSTEM_SHAPE_OWNER, problemId: problem.id },
    };
    const other = { id: "other", type: "note", meta: { owner: SYSTEM_SHAPE_OWNER, problemId: "other" } };
    const { editor, created, deleted, shapes } = makeEditor({ shapes: [legacy, other] });
    expect(ensureProblemShape(editor, problem)).toBe(true);
    expect(deleted).toEqual(["legacy"]);
    expect(created[0]).toMatchObject({ type: PROBLEM_SHAPE_TYPE, x: 240, y: 260 });
    expect(shapes.has("other")).toBe(true);
  });
});
