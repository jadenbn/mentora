/**
 * The animated counterpart to renderCanvasActions.
 *
 * Same input and coordinate rules, with circles drawn as freehand strokes and
 * check/cross marks fading in as the same settled glyphs used during restore.
 */

import { createShapeId } from "tldraw";
import type { Editor, TLDefaultColorStyle } from "tldraw";
import {
  animateTextShape,
  animateStrokes,
  sequence,
  type AnimationHandle,
} from "@/lib/annotations/animate";
import {
  ellipseStroke,
  makeJitter,
  toWorldRect,
  type WorldBounds,
  type Stroke,
} from "@/lib/annotations/geometry";
import {
  AI_SHAPE_OWNER,
  clearAiShapesForInteraction,
  buildMarkShape,
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
    default:
      return null;
  }
}

const COLORS: Partial<Record<CanvasAction["type"], TLDefaultColorStyle>> = {
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

  if (action.type === "check" || action.type === "cross") {
    const shape = buildMarkShape(action, context);
    if (!shape) return null;
    return () => animateTextShape(editor, shape);
  }

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
