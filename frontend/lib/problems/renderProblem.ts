import { createShapeId } from "tldraw";
import type { Editor, TLShapeId, TLShapePartial } from "tldraw";
import { SYSTEM_SHAPE_OWNER } from "@/lib/canvas/ownership";
import { VERTICAL_PAGE_ID } from "@/lib/canvas/verticalPage";
import type { ProblemContext } from "@/types/domain";

export const PROBLEM_SHAPE_TYPE = "mentora-problem";
const PROBLEM_WIDTH = 680;
const PROBLEM_HEIGHT = 180;
const PROBLEM_TOP_PADDING = 64;

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
  const existing = editor.getShape(id);
  for (const shapeId of editor.getCurrentPageShapeIds()) {
    const shape = editor.getShape(shapeId);
    if (shape?.meta?.owner === SYSTEM_SHAPE_OWNER && shape.meta.problemId === problem.id) {
      if (shapeId !== id) legacy.push(shapeId);
    }
  }
  if (legacy.length) editor.deleteShapes(legacy);

  const page = editor.getShape(VERTICAL_PAGE_ID);
  const bounds =
    (page ? editor.getShapePageBounds(page) : undefined) ??
    editor.getViewportPageBounds();
  const x = bounds.x + (bounds.w - PROBLEM_WIDTH) / 2;
  const y = bounds.y + PROBLEM_TOP_PADDING;

  if (existing && isProblem(existing)) {
    const props = existing.props as { w?: unknown; h?: unknown };
    const moved = existing.x !== x || existing.y !== y;
    const resized = props.w !== PROBLEM_WIDTH || props.h !== PROBLEM_HEIGHT;
    if (moved || resized) {
      editor.updateShape({
        id,
        type: PROBLEM_SHAPE_TYPE,
        x,
        y,
        props: { w: PROBLEM_WIDTH, h: PROBLEM_HEIGHT },
      });
    }
    return legacy.length > 0 || moved || resized;
  }

  if (existing) editor.deleteShapes([id]);

  const partial: TLShapePartial = {
    id,
    type: PROBLEM_SHAPE_TYPE,
    x,
    y,
    isLocked: true,
    meta: { owner: SYSTEM_SHAPE_OWNER, problemId: problem.id },
    props: { problemId: problem.id, w: PROBLEM_WIDTH, h: PROBLEM_HEIGHT },
  };
  editor.createShapes([partial]);
  return true;
}
