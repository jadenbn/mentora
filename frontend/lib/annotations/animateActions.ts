/**
 * The animated counterpart to renderCanvasActions.
 *
 * Same input, same coordinate rules, different output: geometry is drawn as
 * freehand strokes rather than perfect geo shapes, because a sketched ellipse
 * next to handwriting reads better than a vector one.
 */

import { createShapeId } from "tldraw";
import type { Editor, TLDefaultColorStyle } from "tldraw";
import {
  animateStrokes,
  sequence,
  type AnimationHandle,
} from "@/lib/annotations/animate";
import {
  checkStrokes,
  crossStrokes,
  ellipseStroke,
  makeJitter,
  toWorldRect,
  type WorldBounds,
  type Stroke,
} from "@/lib/annotations/geometry";
import {
  AI_SHAPE_OWNER,
  clearAiShapesForInteraction,
  type RenderContext,
} from "@/lib/annotations/renderCanvasActions";
import type { CanvasAction } from "@/types/tutor";

/** How far a stroke wanders from its ideal path, in world units. */
const JITTER = 1.6;

function metaFor(context: RenderContext) {
  return { owner: AI_SHAPE_OWNER, interactionId: context.interactionId };
}

/** Deterministic wobble seed from the action itself, so a replay looks identical. */
function seedFor(action: CanvasAction): string {
  return `${action.type}:${action.target.x},${action.target.y}`;
}

/** Strokes for hand-drawn actions; highlights use a translucent region. */
function strokesFor(action: CanvasAction, frame: WorldBounds): Stroke[] | null {
  if (action.type === "highlight") {
    return null;
  }
  const jitter = makeJitter(seedFor(action), JITTER);
  const rect = toWorldRect(action.target, frame);

  switch (action.type) {
    case "circle":
      return [ellipseStroke(rect, jitter)];
    case "check":
      return checkStrokes(rect, jitter);
    case "cross":
      return crossStrokes(rect, jitter);
    default:
      return null;
  }
}

const COLORS: Partial<Record<CanvasAction["type"], TLDefaultColorStyle>> = {
  check: "green",
  highlight: "yellow",
};

function colorFor(action: CanvasAction): TLDefaultColorStyle {
  return COLORS[action.type] ?? "red";
}

function stepFor(
  editor: Editor,
  action: CanvasAction,
  context: RenderContext,
): (() => AnimationHandle) | null {
  const meta = metaFor(context);
  const color = colorFor(action);

  const strokes = strokesFor(action, context.bounds);
  if (strokes) {
    return () => animateStrokes(editor, strokes, { meta, color });
  }

  if (action.type === "highlight") {
    const rect = toWorldRect(action.target, context.bounds);
    return () => {
      editor.run(
        () =>
          editor.createShape({
            id: createShapeId(),
            type: "geo",
            x: rect.x,
            y: rect.y,
            opacity: 0.28,
            meta,
            props: {
              geo: "rectangle",
              w: rect.w,
              h: rect.h,
              color,
              fill: "solid",
              dash: "solid",
              size: "s",
            },
          }),
        { history: "ignore" },
      );
      return { done: Promise.resolve(), cancel: () => {} };
    };
  }

  // Unrecognised action from a newer backend: skip rather than guess.
  return null;
}

/**
 * Draw a tutor's actions in sequence, as if written.
 *
 * Returns a handle so a second request, or the student picking the pen back
 * up, can interrupt an animation already in flight.
 */
export function animateCanvasActions(
  editor: Editor,
  actions: CanvasAction[],
  context: RenderContext,
): AnimationHandle {
  clearAiShapesForInteraction(editor, context.interactionId);

  const steps = actions
    .map((action) => stepFor(editor, action, context))
    .filter((step): step is () => AnimationHandle => step !== null);

  const handle = sequence(steps);

  return {
    done: handle.done,
    cancel: () => handle.cancel(),
  };
}
