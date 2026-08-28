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

/** A closed vocabulary for what went wrong. Optional, and only ever set
 * when status is "incorrect" or "partial" -- see services/tutor_policy.py.
 * Nothing on the frontend reads this yet; it exists to keep the wire
 * mirror accurate. */
export type ErrorTag =
  | "sign_error"
  | "dropped_constant"
  | "wrong_technique"
  | "algebra_slip"
  | "concept_gap";

/** What a mark points with. Text is the only way to put words on the canvas. */
export type MarkType = "circle" | "check" | "cross";

export interface NormalizedPoint {
  x: number;
  y: number;
}

/** Width and height are > 0, and x+width / y+height stay <= 1. */
export interface NormalizedBounds extends NormalizedPoint {
  width: number;
  height: number;
}

/** Say something at a point. */
export interface TextAction {
  type: "text";
  position: NormalizedPoint;
  text: string;
}

/** Point at a region. */
export interface TargetAction {
  type: MarkType;
  target: NormalizedBounds;
}

export type CanvasAction = TextAction | TargetAction;

export interface TutorResponse {
  interaction_id: string;
  status: WorkStatus;
  canvas_actions: CanvasAction[];
  summary: string | null;
  error_tag: ErrorTag | null;
}
