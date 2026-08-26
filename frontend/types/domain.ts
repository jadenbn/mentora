export type TutorMode = "mark" | "hint" | "explain" | "stuck";

export interface Course {
  id: string;
  name: string;
  description: string;
}

/** The topic this generated problem was attributed to, if any --
 * unattributed for a problem the engine could not tie to a topic. */
export interface ProblemSkill {
  skillId: string;
  skillName: string;
}

export interface Problem {
  id: string;
  courseId: string;
  documentId: string;
  source: "generated";
  prompt: string;
  skill?: ProblemSkill;
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
  problem?: Problem;
}
