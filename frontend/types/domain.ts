export type TutorMode = "mark" | "hint" | "explain" | "stuck";

export interface Course {
  id: string;
  name: string;
  description: string;
}

/**
 * A persistent whiteboard document. Called a "space" in the UI.
 *
 * The backend contract still names this `session_id` on the wire (see
 * docs/TUTOR_AGENT.md), so a space's id is sent as the session id.
 */
export interface Space {
  id: string;
  courseId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
}
