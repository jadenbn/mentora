export type TutorMode = "mark" | "hint" | "explain" | "stuck";

export interface Room {
  id: string;
  name: string;
  description: string;
}

/** A persistent whiteboard document, local to the browser. */
export interface Space {
  id: string;
  roomId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
}
