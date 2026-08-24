/** Canonical ownership tags for every kind of whiteboard content. */

export const SYSTEM_SHAPE_OWNER = "system";
export const STUDENT_SHAPE_OWNER = "student";
export const AI_SHAPE_OWNER = "ai";

export type ShapeOwner =
  | typeof SYSTEM_SHAPE_OWNER
  | typeof STUDENT_SHAPE_OWNER
  | typeof AI_SHAPE_OWNER;
