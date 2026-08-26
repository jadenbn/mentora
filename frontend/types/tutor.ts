/**
 * Mirror of the backend tutor contract.
 *
 * Source of truth: backend/app/schemas/tutor.py. The backend uses
 * extra="forbid", so an unknown key is a 422 rather than a silently ignored
 * extra.
 *
 * Coordinates are normalized to the submitted canvas image: x/y in [0, 1] from
 * its top-left. Conversion to tldraw world space happens in exactly one place,
 * lib/annotations/renderCanvasActions.ts.
 */

import type { TutorMode } from "@/types/domain";

export type { TutorMode };

export type WorkStatus = "correct" | "incorrect" | "partial" | "uncertain";

/** Width and height are > 0, and x+width / y+height stay <= 1. */
export interface NormalizedBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Point at or highlight a region. Prose remains in the navbar summary. */
export interface TargetAction {
  type: "highlight" | "circle" | "check" | "cross";
  target: NormalizedBounds;
}

export type CanvasAction = TargetAction;

export interface TutorResponse {
  interaction_id: string;
  status: WorkStatus;
  canvas_actions: CanvasAction[];
  summary: string;
}
