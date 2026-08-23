import type { Course } from "@/types/domain";

/**
 * Courses are hardcoded until the course API exists.
 *
 * `course_demo` is the id the tutor request already sends, and the one the
 * chain-rule lecture was ingested under, so it is the course where grounding
 * actually works today.
 */
export const COURSES: Course[] = [
  {
    id: "course_demo",
    name: "MATH 101",
    description: "Calculus I — limits, derivatives, the chain rule.",
  },
  {
    id: "course_linear",
    name: "MATH 221",
    description: "Linear algebra — vectors, matrices, eigenvalues.",
  },
];

export function getCourse(courseId: string): Course | undefined {
  return COURSES.find((course) => course.id === courseId);
}
