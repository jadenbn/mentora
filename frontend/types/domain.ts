export type TutorMode = "mark" | "hint" | "explain" | "stuck";

export interface Course {
  id: string;
  name: string;
}

export interface WhiteboardSession {
  id: string;
  courseId: string;
  title: string;
  updatedAt: string;
}
