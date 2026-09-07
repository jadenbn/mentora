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
import type {
  Editor,
  TLDefaultColorStyle,
  TLShapePartial,
  TLShapeId,
} from "tldraw";
import type { WorldBounds } from "@/lib/annotations/geometry";
import { toWorldRect } from "@/lib/annotations/geometry";
import type { CanvasAction } from "@/types/tutor";
import { AI_SHAPE_OWNER } from "@/lib/canvas/ownership";

/** Marks every shape this module creates, so tutor output stays identifiable. */
export { AI_SHAPE_OWNER } from "@/lib/canvas/ownership";

export interface RenderContext {
  /** World rectangle the analyzed image covered, from captureCanvasForAnalysis. */
  bounds: WorldBounds;
  interactionId: string;
}

type AiShapeMeta = { owner: typeof AI_SHAPE_OWNER; interactionId: string };

/** How each action draws. Prose never becomes a canvas shape. */
const MARKS: Record<CanvasAction["type"], { glyph?: string; color: TLDefaultColorStyle }> = {
  highlight: { color: "yellow" },
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
  // duplicates. Whiteboard history clears all AI shapes before switching layers.
  clearAiShapesForInteraction(editor, context.interactionId);

  const partials = actions
    .map((action) => buildShape(action, context))
    .filter((partial): partial is TLShapePartial => partial !== null);

  if (partials.length > 0) {
    editor.createShapes(partials);
  }
}

/** Remove one interaction's marks before replacing them, animated or not. */
export function clearAiShapesForInteraction(
  editor: Editor,
  interactionId: string,
): void {
  deleteWhere(
    editor,
    (meta) =>
      meta.owner === AI_SHAPE_OWNER && meta.interactionId === interactionId,
  );
}

export function hasAiShapes(editor: Editor): boolean {
  return [...editor.getCurrentPageShapeIds()].some((id) => {
    const shape = editor.getShape(id);
    return shape?.meta?.owner === AI_SHAPE_OWNER;
  });
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

  const mark = MARKS[action.type];
  if (!mark || !action.target) return null;
  const rect = toWorldRect(action.target, frame);
  if (action.type === "highlight") {
    return {
      id,
      type: "geo" as const,
      x: rect.x,
      y: rect.y,
      opacity: 0.28,
      meta,
      props: {
        geo: "rectangle",
        w: rect.w,
        h: rect.h,
        color: mark.color,
        fill: "solid",
        dash: "solid",
        size: "s",
      },
    };
  }

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

  return buildMarkShape(action, context, { id, meta });
}

/** Build the settled text glyph used by both instant and animated rendering. */
export function buildMarkShape(
  action: CanvasAction,
  context: RenderContext,
  overrides: { id?: TLShapeId; meta?: AiShapeMeta } = {},
) {
  if (action.type !== "check" && action.type !== "cross") return null;
  const mark = MARKS[action.type];
  const rect = toWorldRect(action.target, context.bounds);
  return {
    id: overrides.id ?? createShapeId(),
    type: "text" as const,
    x: rect.x + rect.w,
    y: rect.y,
    meta: overrides.meta ?? {
      owner: AI_SHAPE_OWNER,
      interactionId: context.interactionId,
    },
    props: {
      richText: toRichText(mark.glyph!),
      color: mark.color,
      size: "l" as const,
    },
  };
}
