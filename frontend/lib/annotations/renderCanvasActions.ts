/**
 * Annotation renderer (ARCHITECTURE.md section 19).
 *
 * This module is the ONLY place that converts the tutor's normalized
 * image-space coordinates into tldraw world coordinates. Nothing else in the
 * app should do that arithmetic.
 *
 * The tutor never drives tldraw directly: it returns a validated, closed set of
 * canvas actions, and this file decides what each one looks like on the canvas.
 */

import { createShapeId, toRichText } from "tldraw";
import type { Box, Editor, TLShapeId } from "tldraw";
import type {
  CanvasAction,
  NormalizedBounds,
  NormalizedPoint,
} from "@/types/tutor";

/** Marks every shape this module creates, so AI output stays distinguishable. */
export const AI_SHAPE_OWNER = "ai";

export interface RenderContext {
  /** World-space rectangle the analyzed image covered, from captureCanvasForAnalysis. */
  bounds: Box;
  interactionId: string;
}

interface AiShapeMeta {
  owner: typeof AI_SHAPE_OWNER;
  interactionId: string;
  actionId: string;
  [key: string]: unknown;
}

export function renderCanvasActions(
  editor: Editor,
  actions: CanvasAction[],
  context: RenderContext,
): void {
  // Re-rendering the same interaction replaces its shapes instead of stacking
  // duplicates on top of them (ARCHITECTURE.md section 39).
  clearInteraction(editor, context.interactionId);

  const partials = actions
    .map((action) => buildShape(action, context))
    .filter((partial): partial is NonNullable<typeof partial> => partial !== null);

  if (partials.length > 0) {
    editor.createShapes(partials);
  }
}

/** Remove every AI-authored shape from the current page. */
export function clearAiShapes(editor: Editor): void {
  deleteWhere(editor, (meta) => meta.owner === AI_SHAPE_OWNER);
}

function clearInteraction(editor: Editor, interactionId: string): void {
  deleteWhere(
    editor,
    (meta) =>
      meta.owner === AI_SHAPE_OWNER && meta.interactionId === interactionId,
  );
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

function toWorldPoint(point: NormalizedPoint, frame: Box) {
  return {
    x: frame.x + point.x * frame.w,
    y: frame.y + point.y * frame.h,
  };
}

function toWorldRect(target: NormalizedBounds, frame: Box) {
  return {
    x: frame.x + target.x * frame.w,
    y: frame.y + target.y * frame.h,
    w: Math.max(1, target.width * frame.w),
    h: Math.max(1, target.height * frame.h),
  };
}

function metaFor(action: CanvasAction, context: RenderContext): AiShapeMeta {
  return {
    owner: AI_SHAPE_OWNER,
    interactionId: context.interactionId,
    actionId: action.action_id,
  };
}

function buildShape(action: CanvasAction, context: RenderContext) {
  const frame = context.bounds;
  const id = createShapeId();
  const meta = metaFor(action, context);

  switch (action.type) {
    case "text": {
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

    case "math": {
      // No LaTeX renderer on the canvas yet, so the source is shown verbatim.
      // client_capabilities reports supports_latex: false, so the backend
      // should not normally send this.
      const at = toWorldPoint(action.position, frame);
      return {
        id,
        type: "text" as const,
        x: at.x,
        y: at.y,
        meta,
        props: { richText: toRichText(action.latex), color: "violet", size: "m" },
      };
    }

    case "arrow": {
      const from = toWorldPoint(action.start, frame);
      const to = toWorldPoint(action.end, frame);
      return {
        id,
        type: "arrow" as const,
        x: from.x,
        y: from.y,
        meta,
        props: {
          start: { x: 0, y: 0 },
          end: { x: to.x - from.x, y: to.y - from.y },
          color: "red",
          size: "m",
          arrowheadStart: "none",
          arrowheadEnd: "arrow",
          ...(action.label ? { richText: toRichText(action.label) } : {}),
        },
      };
    }

    case "circle": {
      const rect = toWorldRect(action.target, frame);
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
          color: "red",
          fill: "none",
          dash: "draw",
          size: "m",
          ...(action.label ? { richText: toRichText(action.label) } : {}),
        },
      };
    }

    case "highlight": {
      const rect = toWorldRect(action.target, frame);
      return {
        id,
        type: "geo" as const,
        x: rect.x,
        y: rect.y,
        meta,
        props: {
          geo: "rectangle",
          w: rect.w,
          h: rect.h,
          color: "yellow",
          fill: "semi",
          dash: "solid",
          size: "s",
          ...(action.label ? { richText: toRichText(action.label) } : {}),
        },
      };
    }

    case "underline": {
      // A headless arrow along the bottom edge reads as a rule under the work.
      const rect = toWorldRect(action.target, frame);
      return {
        id,
        type: "arrow" as const,
        x: rect.x,
        y: rect.y + rect.h,
        meta,
        props: {
          start: { x: 0, y: 0 },
          end: { x: rect.w, y: 0 },
          color: "red",
          size: "s",
          arrowheadStart: "none",
          arrowheadEnd: "none",
          ...(action.label ? { richText: toRichText(action.label) } : {}),
        },
      };
    }

    case "check":
      return markShape(id, meta, action.target, frame, "✓", "green");

    case "cross":
      return markShape(id, meta, action.target, frame, "✗", "red");

    default:
      // Unknown action type from a newer backend: skip it rather than guess.
      return null;
  }
}

/** A check or cross, placed just past the top-right corner of the target. */
function markShape(
  id: TLShapeId,
  meta: AiShapeMeta,
  target: NormalizedBounds,
  frame: Box,
  glyph: string,
  color: string,
) {
  const rect = toWorldRect(target, frame);
  return {
    id,
    type: "text" as const,
    x: rect.x + rect.w,
    y: rect.y,
    meta,
    props: { richText: toRichText(glyph), color, size: "l" },
  };
}
