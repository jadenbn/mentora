import { describe, expect, it } from "vitest";
import { ensureProblemShape, SYSTEM_SHAPE_OWNER } from "@/lib/problems/renderProblem";
import { makeEditor } from "./fakeEditor";

const problem = {
  id: "problem_123",
  courseId: "course_demo",
  documentId: "doc_1",
  source: "generated" as const,
  prompt: "Find the derivative of x².",
};

describe("ensureProblemShape", () => {
  it("creates one locked system-owned note", () => {
    const fake = makeEditor();
    expect(ensureProblemShape(fake.editor, problem)).toBe(true);
    expect(fake.created).toHaveLength(1);
    expect(fake.created[0]).toMatchObject({
      type: "note",
      isLocked: true,
      meta: { owner: SYSTEM_SHAPE_OWNER, problemId: problem.id },
    });
  });

  it("does not duplicate a restored problem shape", () => {
    const fake = makeEditor({
      shapes: [{
        id: "restored",
        type: "note",
        meta: { owner: SYSTEM_SHAPE_OWNER, problemId: problem.id },
      }],
    });
    expect(ensureProblemShape(fake.editor, problem)).toBe(false);
    expect(fake.created).toHaveLength(0);
  });
});
