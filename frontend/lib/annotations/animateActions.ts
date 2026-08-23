/**
 * The animated counterpart to renderCanvasActions.
 *
 * Same input, same coordinate rules, different output: geometry is drawn as
 * freehand strokes rather than perfect geo shapes, because a sketched ellipse
 * next to handwriting reads better than a vector one.
 */

import type { Box, Editor, TLDefaultColorStyle, TLShapeId } from "tldraw";
import {
  animateStrokes,
  animateText,
  sequence,
  type AnimationHandle,
} from "@/lib/annotations/animate";
import {
  checkStrokes,
  crossStrokes,
  ellipseStroke,
  makeJitter,
  toWorldPoint,
  toWorldRect,
  type Stroke,
} from "@/lib/annotations/geometry";
import { AI_SHAPE_OWNER } from "@/lib/annotations/renderCanvasActions";
import type { CanvasAction } from "@/types/tutor";

/** How far a stroke wanders from its ideal path, in world units. */
const JITTER = 1.6;

export interface AnimateContext {
  bounds: Box;
  interactionId: string;
}

function metaFor(context: AnimateContext) {
  return { owner: AI_SHAPE_OWNER, interactionId: context.interactionId };
}

/** Deterministic wobble seed from the action itself, so a replay looks identical. */
function seedFor(action: CanvasAction): string {
  switch (action.type) {
    case "text":
      return `text:${action.position.x},${action.position.y}:${action.text}`;
    case "circle":
    case "check":
    case "cross":
      return `${action.type}:${action.target.x},${action.target.y}`;
    default:
      return action.type;
  }
}

/** Strokes for the geometric actions; null for the text-shaped ones. */
function strokesFor(action: CanvasAction, frame: Box): Stroke[] | null {
  switch (action.type) {
    case "circle": {
      const jitter = makeJitter(seedFor(action), JITTER);
      const rect = toWorldRect(action.target, frame);
      return [ellipseStroke(rect, jitter)];
    }
    case "check": {
      const jitter = makeJitter(seedFor(action), JITTER);
      const rect = toWorldRect(action.target, frame);
      return checkStrokes(rect, jitter);
    }
    case "cross": {
      const jitter = makeJitter(seedFor(action), JITTER);
      const rect = toWorldRect(action.target, frame);
      return crossStrokes(rect, jitter);
    }
    default:
      return null;
  }
}

const COLORS: Partial<Record<CanvasAction["type"], TLDefaultColorStyle>> = {
  check: "green",
};

function colorFor(action: CanvasAction): TLDefaultColorStyle {
  return COLORS[action.type] ?? "red";
}

function stepFor(
  editor: Editor,
  action: CanvasAction,
  context: AnimateContext,
  onShape: (id: TLShapeId) => void,
): (() => AnimationHandle) | null {
  const meta = metaFor(context);
  const color = colorFor(action);

  const strokes = strokesFor(action, context.bounds);
  if (strokes) {
    return () => animateStrokes(editor, strokes, { meta, color, onShape });
  }

  if (action.type === "text") {
    const at = toWorldPoint(action.position, context.bounds);
    return () => animateText(editor, at, action.text, { meta, color, onShape });
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
  context: AnimateContext,
): AnimationHandle {
  const drawn: TLShapeId[] = [];
  const onShape = (id: TLShapeId) => drawn.push(id);

  const steps = actions
    .map((action) => stepFor(editor, action, context, onShape))
    .filter((step): step is () => AnimationHandle => step !== null);

  const handle = sequence(steps);

  return {
    done: handle.done,
    cancel: () => handle.cancel(),
  };
}
