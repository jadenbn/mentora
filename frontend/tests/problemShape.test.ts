import { describe, expect, it } from "vitest";
import { ensureProblemShape, problemShapeId, PROBLEM_SHAPE_TYPE } from "@/lib/problems/renderProblem";
import { SYSTEM_SHAPE_OWNER } from "@/lib/canvas/ownership";
import { VERTICAL_PAGE_ID } from "@/lib/canvas/verticalPage";
import { box, makeEditor } from "./fakeEditor";

const problem = {
  id: "problem_1",
  course_id: "course_1",
  document_id: "doc_1",
  source: "generated" as const,
  prompt: "Solve $x=1$.",
};

const page = {
  id: VERTICAL_PAGE_ID,
  type: "geo",
  pageBounds: box(100, 200, 900, 1_400),
};

describe("ensureProblemShape", () => {
  it("creates one locked system-owned shape centered near the top of the page", () => {
    const { editor, created } = makeEditor({ shapes: [page] });
    expect(ensureProblemShape(editor, problem)).toBe(true);
    expect(created[0]).toMatchObject({
      id: problemShapeId(problem.id),
      type: PROBLEM_SHAPE_TYPE,
      x: 210,
      y: 264,
      isLocked: true,
      meta: { owner: SYSTEM_SHAPE_OWNER, problemId: problem.id },
      props: { problemId: problem.id, w: 680, h: 180 },
    });
  });

  it("is idempotent after the shape is restored", () => {
    const first = makeEditor({ shapes: [page] });
    ensureProblemShape(first.editor, problem);
    const second = makeEditor({
      shapes: [
        page,
        {
          id: problemShapeId(problem.id),
          type: PROBLEM_SHAPE_TYPE,
          x: 210,
          y: 264,
          props: { problemId: problem.id, w: 680, h: 180 },
        },
      ],
    });
    expect(ensureProblemShape(second.editor, problem)).toBe(false);
    expect(second.created).toHaveLength(0);
  });

  it("recenters a problem restored at an old viewport-relative position", () => {
    const id = problemShapeId(problem.id);
    const { editor, shapes } = makeEditor({
      shapes: [
        page,
        {
          id,
          type: PROBLEM_SHAPE_TYPE,
          x: -120,
          y: 20,
          props: { problemId: problem.id, w: 680, h: 180 },
        },
      ],
    });

    expect(ensureProblemShape(editor, problem)).toBe(true);
    expect(shapes.get(id)).toMatchObject({ x: 210, y: 264 });
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
    const { editor, created, deleted, shapes } = makeEditor({
      shapes: [page, legacy, other],
    });
    expect(ensureProblemShape(editor, problem)).toBe(true);
    expect(deleted).toEqual(["legacy"]);
    expect(created[0]).toMatchObject({ type: PROBLEM_SHAPE_TYPE, x: 210, y: 264 });
    expect(shapes.has("other")).toBe(true);
  });
});
