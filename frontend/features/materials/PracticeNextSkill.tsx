"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Sparkles } from "lucide-react";
import { fetchNextProblem, TutorApiError } from "@/lib/api/api";
import { getStudentId } from "@/lib/student/identity";
import { createSpace } from "@/lib/spaces/store";

/**
 * The learning-engine entry point: let selection pick what to practice next,
 * rather than the student choosing a document and typing a request.
 *
 * A course with ingested documents but no skills yet bootstraps its first
 * skill on the first click here — see backend next_problem's cold-start path
 * — so the same button both starts and continues the loop.
 */
export function PracticeNextSkill({ courseId }: { courseId: string }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const studentId = getStudentId();
      const problem = await fetchNextProblem(courseId, studentId);
      const title = problem.skill ? `Practice — ${problem.skill.skillName}` : "Practice";
      const space = createSpace(courseId, title, problem);
      router.push(`/spaces/${space.id}`);
    } catch (caught) {
      if (caught instanceof TutorApiError && caught.status === 404) {
        setError(
          "Nothing ready to practice yet. Upload a course document above, then try again.",
        );
      } else if (caught instanceof TutorApiError && caught.status === 409) {
        setError("This course has no indexed documents to ground a question in yet.");
      } else {
        setError(caught instanceof Error ? caught.message : "Could not select a problem.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="border-b border-slate-200 py-6" aria-labelledby="practice-heading">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 id="practice-heading" className="text-xl font-bold text-slate-950">
            Practice
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            Let the engine pick the next skill and generate a grounded question for it.
          </p>
        </div>
        <button
          className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800 disabled:bg-slate-400"
          disabled={loading}
          onClick={() => void handleClick()}
          type="button"
        >
          <Sparkles aria-hidden="true" className="size-4" />
          {loading ? "Selecting…" : "Practice next skill"}
        </button>
      </div>
      {error ? (
        <p className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      ) : null}
    </section>
  );
}
