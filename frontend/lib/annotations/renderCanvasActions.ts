/**
 * The annotation renderer.
 *
 * The only place normalized image coordinates become tldraw world
 * coordinates. Nothing else in the app should do that arithmetic.
 *
 * The tutor never drives tldraw: it returns a closed set of validated actions,
 * and this file decides what each one looks like on the canvas.
 */

import { createShapeId, toRichText } from "tldraw";
import type { Box, Editor, TLShapePartial, TLShapeId } from "tldraw";
import { toWorldPoint, toWorldRect } from "@/lib/annotations/geometry";
import type { CanvasAction, MarkType } from "@/types/tutor";

/** Marks every shape this module creates, so tutor output stays identifiable. */
export const AI_SHAPE_OWNER = "ai";

export interface RenderContext {
  /** World rectangle the analyzed image covered, from captureCanvasForAnalysis. */
  bounds: Box;
  interactionId: string;
}

type AiShapeMeta = { owner: typeof AI_SHAPE_OWNER; interactionId: string };

/** How each mark draws. Circling outlines; a check or cross is a glyph. */
const MARKS: Record<MarkType, { glyph?: string; color: string }> = {
  circle: { color: "red" },
  check: { glyph: "✓", color: "green" },
  cross: { glyph: "✗", color: "red" },
};

export function renderCanvasActions(
  editor: Editor,
  actions: CanvasAction[],
  context: RenderContext,
): void {
  // Re-rendering one interaction replaces its shapes rather than stacking
  // duplicates. Feedback from other interactions is left alone, so a follow-up
  // does not wipe the conversation it is continuing.
  deleteWhere(
    editor,
    (meta) =>
      meta.owner === AI_SHAPE_OWNER && meta.interactionId === context.interactionId,
  );

  const partials = actions
    .map((action) => buildShape(action, context))
    .filter((partial): partial is TLShapePartial => partial !== null);

  if (partials.length > 0) {
    editor.createShapes(partials);
  }
}

/** Remove every tutor-authored shape from the current page. */
export function clearAiShapes(editor: Editor): void {
  deleteWhere(editor, (meta) => meta.owner === AI_SHAPE_OWNER);
}

function deleteWhere(
  editor: Editor,
  predicate: (meta: Record<string, unknown>) => boolean,
): void {
  const doomed: TLShapeId[] = [];
  for (const id of editor.getCurrentPageShapeIds()) {
    const shape = editor.getShape(id);
    if (shape && predicate(shape.meta ?? {})) {
      doomed.push(id);
    }
  }
  if (doomed.length > 0) {
    editor.deleteShapes(doomed);
  }
}

function buildShape(
  action: CanvasAction,
  context: RenderContext,
): TLShapePartial | null {
  const frame = context.bounds;
  const id = createShapeId();
  const meta: AiShapeMeta = {
    owner: AI_SHAPE_OWNER,
    interactionId: context.interactionId,
  };

  if (action.type === "text") {
    const at = toWorldPoint(action.position, frame);
    return {
      id,
      type: "text" as const,
      x: at.x,
      y: at.y,
      meta,
      props: { richText: toRichText(action.text), color: "red", size: "m" },
    };
  }

  const mark = MARKS[action.type as MarkType];
  if (!mark) {
    // An action type from a newer backend: skip it rather than guess.
    return null;
  }

  const rect = toWorldRect(action.target, frame);
  if (!mark.glyph) {
    return {
      id,
      type: "geo" as const,
      x: rect.x,
      y: rect.y,
      meta,
      props: {
        geo: "ellipse",
        w: rect.w,
        h: rect.h,
        color: mark.color,
        fill: "none",
        dash: "draw",
        size: "m",
      },
    };
  }

  // A check or cross sits just past the top-right corner of what it marks.
  return {
    id,
    type: "text" as const,
    x: rect.x + rect.w,
    y: rect.y,
    meta,
    props: { richText: toRichText(mark.glyph), color: mark.color, size: "l" },
  };
}
