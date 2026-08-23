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
  arrowStrokes,
  checkStrokes,
  crossStrokes,
  ellipseStroke,
  makeJitter,
  rectangleStroke,
  toWorldPoint,
  toWorldRect,
  underlineStrokes,
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

function metaFor(action: CanvasAction, context: AnimateContext) {
  return {
    owner: AI_SHAPE_OWNER,
    interactionId: context.interactionId,
    actionId: action.action_id,
  };
}

/** Strokes for the geometric actions; null for the text-shaped ones. */
function strokesFor(action: CanvasAction, frame: Box): Stroke[] | null {
  const jitter = makeJitter(action.action_id, JITTER);

  switch (action.type) {
    case "circle":
      return [ellipseStroke(toWorldRect(action.target, frame), jitter)];
    case "highlight":
      return [rectangleStroke(toWorldRect(action.target, frame), jitter)];
    case "underline":
      return underlineStrokes(toWorldRect(action.target, frame), jitter);
    case "check":
      return checkStrokes(toWorldRect(action.target, frame), jitter);
    case "cross":
      return crossStrokes(toWorldRect(action.target, frame), jitter);
    case "arrow":
      return arrowStrokes(
        toWorldPoint(action.start, frame),
        toWorldPoint(action.end, frame),
        jitter,
      );
    default:
      return null;
  }
}

const COLORS: Partial<Record<CanvasAction["type"], TLDefaultColorStyle>> = {
  check: "green",
  highlight: "yellow",
  math: "violet",
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
  const meta = metaFor(action, context);
  const color = colorFor(action);

  const strokes = strokesFor(action, context.bounds);
  if (strokes) {
    return () => animateStrokes(editor, strokes, { meta, color, onShape });
  }

  if (action.type === "text" || action.type === "math") {
    const body = action.type === "text" ? action.text : action.latex;
    const at = toWorldPoint(action.position, context.bounds);
    return () => animateText(editor, at, body, { meta, color, onShape });
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
