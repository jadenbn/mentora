export type TutorMode = "mark" | "hint" | "explain" | "stuck";

export interface Course {
  id: string;
  name: string;
  description: string;
}

/** A persistent whiteboard document, local to the browser. */
export interface Space {
  id: string;
  courseId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
}
