export type TutorMode = "mark" | "hint" | "explain" | "stuck";

export interface Course {
  id: string;
  name: string;
  description: string;
}

/** Generated-problem contract shared by question generation, Spaces, and tutor requests. */
export interface ProblemContext {
  id: string;
  course_id: string;
  document_id: string;
  source: "generated";
  prompt: string;
}

export type DocumentType =
  | "lecture"
  | "assignment"
  | "exam"
  | "practice_exam"
  | "syllabus"
  | "formula_sheet"
  | "other";

export interface CourseDocument {
  document_id: string;
  course_id: string;
  filename: string;
  document_type: DocumentType;
  total_chunks: number;
  total_pages: number;
  extracted_characters: number;
  created_at: string;
  updated_at: string;
}

/** A persistent whiteboard document, local to the browser. */
export interface Space {
  id: string;
  courseId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  problem?: ProblemContext;
}
