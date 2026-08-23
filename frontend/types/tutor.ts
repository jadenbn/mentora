/**
 * TypeScript mirror of the backend tutor contract (schema_version "1.0").
 *
 * Source of truth: backend/app/schemas/tutor.py and docs/TUTOR_AGENT.md.
 * The backend models use `extra="forbid"`, so never send fields that are not
 * declared here — an unknown key is a 422, not a silently ignored extra.
 *
 * Every coordinate below is normalized against the submitted canvas image:
 * x/y in [0, 1] from the image's top-left. Conversion to tldraw world space
 * happens in exactly one place, lib/annotations/renderCanvasActions.ts.
 */

import type { TutorMode } from "@/types/domain";

export type { TutorMode };

export type TutorTrigger = "manual" | "live" | "voice";
export type ShapeOwner = "system" | "student" | "ai";
export type WorkStatus = "correct" | "incorrect" | "partial" | "uncertain";

export type CanvasActionType =
  | "text"
  | "math"
  | "arrow"
  | "circle"
  | "underline"
  | "highlight"
  | "check"
  | "cross";

export interface NormalizedPoint {
  x: number;
  y: number;
}

/** Width and height are strictly positive, and x+width / y+height stay <= 1. */
export interface NormalizedBounds extends NormalizedPoint {
  width: number;
  height: number;
}

export interface Viewport {
  x: number;
  y: number;
  width: number;
  height: number;
  zoom: number;
}

export interface CanvasShape {
  id: string;
  owner: ShapeOwner;
  shape_type: string;
  bounds?: NormalizedBounds | null;
  text?: string | null;
  latex?: string | null;
}

export interface CanvasContext {
  image_width: number;
  image_height: number;
  viewport?: Viewport | null;
  shapes: CanvasShape[];
}

export interface AiSelection {
  shape_ids: string[];
  bounds: NormalizedBounds;
}

export interface ProblemContext {
  prompt_text: string;
  latex_blocks?: string[];
  topic?: string | null;
  difficulty?: string | null;
  expected_skills?: string[];
  source?: "generated" | "imported" | "manual";
}

export interface CourseMetadata {
  name?: string | null;
  covered_topics?: string[];
  not_yet_covered_topics?: string[];
  notation_summary?: string | null;
  instructor_style_summary?: string | null;
}

export interface PriorTutorInteraction {
  interaction_id: string;
  mode: TutorMode;
  summary: string;
  created_at?: string | null;
}

export interface StudentModelSnapshot {
  attempted_topics?: string[];
  recurring_mistakes?: string[];
  strengths?: string[];
  total_hints_used?: number;
}

export interface ClientCapabilities {
  supported_actions: CanvasActionType[];
  supports_latex: boolean;
  supports_selection_crop: boolean;
}

export interface TutorRequest {
  schema_version: "1.0";
  request_id: string;
  user_id: string;
  course_id: string;
  session_id: string;
  problem_id: string;
  mode: TutorMode;
  trigger?: TutorTrigger;
  problem: ProblemContext;
  course?: CourseMetadata;
  canvas: CanvasContext;
  selection?: AiSelection | null;
  recent_interactions?: PriorTutorInteraction[];
  student_model?: StudentModelSnapshot | null;
  transcript?: string | null;
  instruction?: string | null;
  locale?: string;
  timezone?: string | null;
  client_capabilities?: ClientCapabilities;
}

interface CanvasActionBase {
  action_id: string;
  purpose?: string | null;
}

export interface TextAction extends CanvasActionBase {
  type: "text";
  position: NormalizedPoint;
  text: string;
}

export interface MathAction extends CanvasActionBase {
  type: "math";
  position: NormalizedPoint;
  latex: string;
}

export interface ArrowAction extends CanvasActionBase {
  type: "arrow";
  start: NormalizedPoint;
  end: NormalizedPoint;
  label?: string | null;
}

interface TargetAction extends CanvasActionBase {
  target: NormalizedBounds;
  label?: string | null;
}

export interface CircleAction extends TargetAction {
  type: "circle";
}
export interface UnderlineAction extends TargetAction {
  type: "underline";
}
export interface HighlightAction extends TargetAction {
  type: "highlight";
}
export interface CheckAction extends TargetAction {
  type: "check";
}
export interface CrossAction extends TargetAction {
  type: "cross";
}

export type CanvasAction =
  | TextAction
  | MathAction
  | ArrowAction
  | CircleAction
  | UnderlineAction
  | HighlightAction
  | CheckAction
  | CrossAction;

export interface GroundingReference {
  filename: string;
  page: number;
  score: number;
}

export interface CourseBoundaryDecision {
  requires_confirmation: boolean;
  technique?: string | null;
  message?: string | null;
  alternatives_available: boolean;
}

export interface LearningDelivery {
  status: string;
  event_count: number;
}

export interface TutorResponse {
  schema_version: "1.0";
  interaction_id: string;
  request_id: string;
  status: WorkStatus;
  confidence: number;
  canvas_actions: CanvasAction[];
  summary?: string | null;
  grounding_references: GroundingReference[];
  warnings: string[];
  course_boundary: CourseBoundaryDecision;
  learning_events: unknown[];
  learning_delivery: LearningDelivery;
}
