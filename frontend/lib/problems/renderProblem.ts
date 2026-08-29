import { createShapeId } from "tldraw";
import type { Editor, TLShapeId, TLShapePartial } from "tldraw";
import { SYSTEM_SHAPE_OWNER } from "@/lib/canvas/ownership";
import type { ProblemContext } from "@/types/domain";

export const PROBLEM_SHAPE_TYPE = "mentora-problem";

function isProblem(shape: { type: string; meta?: Record<string, unknown> } | undefined): boolean {
  return shape?.type === PROBLEM_SHAPE_TYPE;
}
export function problemShapeId(problemId: string): TLShapeId {
  return createShapeId(`problem-${problemId}`);
}

/** Reconcile one canonical problem into the restored tldraw document. */
export function ensureProblemShape(editor: Editor, problem: ProblemContext): boolean {
  const id = problemShapeId(problem.id);
  const legacy: TLShapeId[] = [];
  let existing = editor.getShape(id);
  for (const shapeId of editor.getCurrentPageShapeIds()) {
    const shape = editor.getShape(shapeId);
    if (shape?.meta?.owner === SYSTEM_SHAPE_OWNER && shape.meta.problemId === problem.id) {
      if (shapeId !== id) legacy.push(shapeId);
      if (!existing) existing = shape;
    }
  }
  if (legacy.length) editor.deleteShapes(legacy);

  if (existing && isProblem(existing)) return legacy.length > 0;

  const viewport = editor.getViewportPageBounds();
  const partial: TLShapePartial = {
    id,
    type: PROBLEM_SHAPE_TYPE,
    x: existing?.x ?? viewport.x + 80,
    y: existing?.y ?? viewport.y + 80,
    isLocked: true,
    meta: { owner: SYSTEM_SHAPE_OWNER, problemId: problem.id },
    props: { problemId: problem.id, w: 680, h: 180 },
  };
  editor.createShapes([partial]);
  return true;
}
