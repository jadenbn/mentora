import { describe, expect, it } from "vitest";
import { SYSTEM_SHAPE_OWNER } from "@/lib/canvas/ownership";
import { removeLegacyProblemShape } from "@/lib/problems/renderProblem";
import { makeEditor } from "./fakeEditor";

const problem = {
  id: "problem_123",
  courseId: "course_demo",
  documentId: "doc_1",
  source: "generated" as const,
  prompt: "Find the derivative of x².",
};

describe("removeLegacyProblemShape", () => {
  it("does nothing when a session has no legacy problem note", () => {
    const fake = makeEditor();
    expect(removeLegacyProblemShape(fake.editor, problem.id)).toBe(false);
    expect(fake.deleted).toHaveLength(0);
  });

  it("removes the old note for the current problem", () => {
    const fake = makeEditor({
      shapes: [{
        id: "restored",
        type: "note",
        meta: { owner: SYSTEM_SHAPE_OWNER, problemId: problem.id },
      }],
    });
    expect(removeLegacyProblemShape(fake.editor, problem.id)).toBe(true);
    expect(fake.deleted).toEqual(["restored"]);
  });

  it("leaves other system content and other problems untouched", () => {
    const fake = makeEditor({
      shapes: [
        {
          id: "other-problem",
          type: "note",
          meta: { owner: SYSTEM_SHAPE_OWNER, problemId: "problem_999" },
        },
        {
          id: "diagram",
          type: "geo",
          meta: { owner: SYSTEM_SHAPE_OWNER },
        },
      ],
    });
    expect(removeLegacyProblemShape(fake.editor, problem.id)).toBe(false);
    expect(fake.deleted).toHaveLength(0);
  });
});
