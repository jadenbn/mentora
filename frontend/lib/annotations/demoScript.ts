/**
 * A scripted end-to-end tutoring session, for demos.
 *
 * Nothing here talks to the backend. It replays the shape of a real session —
 * problem posed, student works, student errs, tutor marks, hints, explains,
 * student corrects, tutor confirms — using the same animation primitives and
 * the same `system | student | ai` ownership the real flow uses.
 *
 * The problem is the chain rule, matching the lecture ingested into
 * course_demo, so the demo lines up with the course the tutor is grounded in.
 */

import type { Box, Editor, TLDefaultColorStyle, TLShapeId } from "tldraw";
import {
  animateStrokes,
  animateText,
  sequence,
  wait,
  type AnimationHandle,
} from "@/lib/annotations/animate";
import {
  checkStrokes,
  crossStrokes,
  ellipseStroke,
  makeJitter,
  toWorldPoint,
  toWorldRect,
  underlineStrokes,
  type Stroke,
} from "@/lib/annotations/geometry";
import type { NormalizedBounds, NormalizedPoint } from "@/types/tutor";

/** Marks everything this script creates, so a rerun can clear only its own. */
export const DEMO_META_FLAG = "demoScript";

type Owner = "system" | "student" | "ai";
type MarkKind = "circle" | "underline" | "check" | "cross";

interface WriteStep {
  kind: "write";
  owner: Owner;
  at: NormalizedPoint;
  text: string;
  color?: TLDefaultColorStyle;
  phase?: string;
}

interface MarkStep {
  kind: "mark";
  mark: MarkKind;
  target: NormalizedBounds;
  color?: TLDefaultColorStyle;
  phase?: string;
}

interface PauseStep {
  kind: "pause";
  ms: number;
  phase?: string;
}

type DemoStep = WriteStep | MarkStep | PauseStep;

/** Vertical rhythm for the worked solution, in normalized viewport space. */
const LEFT = 0.08;
const TUTOR_X = 0.52;
const LINE = (n: number) => 0.1 + n * 0.085;

const SCRIPT: DemoStep[] = [
  {
    kind: "write",
    owner: "system",
    at: { x: LEFT, y: LINE(0) },
    text: "Find dz/dt  where  z = x^2 y,  x = t^3,  y = t^2",
    color: "black",
    phase: "Problem",
  },
  { kind: "pause", ms: 700, phase: "Student working" },

  {
    kind: "write",
    owner: "student",
    at: { x: LEFT, y: LINE(1.4) },
    text: "dz/dt = 2xy (dx/dt) + x^2 (dy/dt)",
    color: "blue",
  },
  { kind: "pause", ms: 350 },
  {
    kind: "write",
    owner: "student",
    at: { x: LEFT, y: LINE(2.4) },
    text: "= 2(t^3)(t^2)(3t^2) + (t^3)^2 (2t)",
    color: "blue",
  },
  { kind: "pause", ms: 350 },
  {
    kind: "write",
    owner: "student",
    at: { x: LEFT, y: LINE(3.4) },
    text: "= 6t^7 + 2t^7",
    color: "blue",
  },
  { kind: "pause", ms: 350 },
  {
    // The deliberate slip: the exponent should not change when adding like terms.
    kind: "write",
    owner: "student",
    at: { x: LEFT, y: LINE(4.4) },
    text: "= 8t^8",
    color: "blue",
  },
  { kind: "pause", ms: 900, phase: "Mark" },

  {
    kind: "mark",
    mark: "cross",
    target: { x: LEFT + 0.14, y: LINE(4.4) - 0.005, width: 0.03, height: 0.03 },
  },
  {
    kind: "write",
    owner: "ai",
    at: { x: TUTOR_X, y: LINE(4.4) },
    text: "The last step is not right",
  },
  { kind: "pause", ms: 1100, phase: "Hint" },

  {
    kind: "mark",
    mark: "circle",
    target: { x: LEFT - 0.01, y: LINE(3.4) - 0.02, width: 0.2, height: 0.07 },
  },
  {
    kind: "write",
    owner: "ai",
    at: { x: TUTOR_X, y: LINE(3.4) },
    text: "What happens to the exponent here?",
  },
  { kind: "pause", ms: 1300, phase: "Explain" },

  {
    kind: "write",
    owner: "ai",
    at: { x: TUTOR_X, y: LINE(2.2) },
    text: "Adding like terms adds the coefficients only:\n6t^7 + 2t^7 = (6 + 2) t^7",
  },
  { kind: "pause", ms: 1400, phase: "Student corrects" },

  {
    kind: "write",
    owner: "student",
    at: { x: LEFT, y: LINE(5.4) },
    text: "= 8t^7",
    color: "blue",
  },
  { kind: "pause", ms: 700, phase: "Mark" },

  {
    kind: "mark",
    mark: "underline",
    target: { x: LEFT, y: LINE(5.4) - 0.005, width: 0.1, height: 0.035 },
    color: "green",
  },
  {
    kind: "mark",
    mark: "check",
    target: { x: LEFT + 0.11, y: LINE(5.4) - 0.005, width: 0.03, height: 0.03 },
    color: "green",
  },
  {
    kind: "write",
    owner: "ai",
    at: { x: TUTOR_X, y: LINE(5.4) },
    text: "That's it — nice recovery",
    color: "green",
    phase: "Done",
  },
];

function markStrokes(step: MarkStep, frame: Box): Stroke[] {
  const jitter = makeJitter(`${step.mark}${step.target.x}${step.target.y}`, 1.6);
  const rect = toWorldRect(step.target, frame);
  switch (step.mark) {
    case "circle":
      return [ellipseStroke(rect, jitter)];
    case "underline":
      return underlineStrokes(rect, jitter);
    case "check":
      return checkStrokes(rect, jitter);
    case "cross":
      return crossStrokes(rect, jitter);
  }
}

/** Remove whatever a previous run of this script left behind. */
export function clearDemoShapes(editor: Editor): void {
  const doomed: TLShapeId[] = [];
  for (const id of editor.getCurrentPageShapeIds()) {
    const shape = editor.getShape(id);
    if (shape?.meta?.[DEMO_META_FLAG]) {
      doomed.push(id);
    }
  }
  if (doomed.length > 0) {
    editor.run(() => editor.deleteShapes(doomed), { history: "ignore" });
  }
}

export interface DemoScriptOptions {
  /** Reports the current beat, so the UI can caption what is happening. */
  onPhase?: (phase: string) => void;
}

export function runDemoScript(
  editor: Editor,
  frame: Box,
  options: DemoScriptOptions = {},
): AnimationHandle {
  clearDemoShapes(editor);

  const steps = SCRIPT.map((step) => () => {
    if (step.phase) {
      options.onPhase?.(step.phase);
    }

    if (step.kind === "pause") {
      return wait(step.ms);
    }

    if (step.kind === "write") {
      const meta = { owner: step.owner, [DEMO_META_FLAG]: true };
      return animateText(editor, toWorldPoint(step.at, frame), step.text, {
        meta,
        color: step.color ?? "red",
        // The student writes at a human pace; the tutor answers briskly.
        charMs: step.owner === "student" ? 34 : 22,
      });
    }

    return animateStrokes(editor, markStrokes(step, frame), {
      meta: { owner: "ai", [DEMO_META_FLAG]: true },
      color: step.color ?? "red",
    });
  });

  return sequence(steps);
}
