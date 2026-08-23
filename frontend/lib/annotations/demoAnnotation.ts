/**
 * Test-only helper: a random tutor-shaped response, used by the "Animate test
 * note" button to exercise the animated renderer without a backend.
 */

import type { Box } from "tldraw";
import type { CanvasAction } from "@/types/tutor";

const PHRASES = [
  "Check this sign",
  "What happens to the exponent?",
  "Nice — the setup is right",
  "Try the chain rule here",
  "This term drops out",
  "Careful: dx/dt, not dx",
  "Factor before simplifying",
  "Almost — one step missing",
];

function pick<T>(items: T[]): T {
  return items[Math.floor(Math.random() * items.length)];
}

/** A random point comfortably inside the frame, leaving room to write. */
function somewhere(): { x: number; y: number } {
  return {
    x: 0.15 + Math.random() * 0.4,
    y: 0.2 + Math.random() * 0.5,
  };
}

/**
 * One text annotation plus a matching mark, so both animation paths run:
 * typewriter for the words, freehand strokes for the geometry.
 */
export function randomDemoActions(): CanvasAction[] {
  const at = somewhere();
  const mark = pick(["circle", "underline", "check", "cross"] as const);
  const stamp = Math.random().toString(36).slice(2, 8);

  return [
    {
      action_id: `demo_${stamp}_mark`,
      type: mark,
      target: { x: at.x, y: at.y + 0.08, width: 0.18, height: 0.06 },
    } as CanvasAction,
    {
      action_id: `demo_${stamp}_text`,
      type: "text",
      position: at,
      text: pick(PHRASES),
    } as CanvasAction,
  ];
}

/** The whole visible canvas, so demo annotations land where you are looking. */
export function viewportFrame(viewport: Box): Box {
  return viewport;
}
