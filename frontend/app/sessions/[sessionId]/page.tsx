import Link from "next/link";
import {
  Whiteboard,
  type WhiteboardProblem,
} from "@/features/whiteboard/Whiteboard";

export default async function SessionPage({
  params,
  searchParams,
}: {
  params: Promise<{ sessionId: string }>;
  searchParams: Promise<{ courseId?: string }>;
}) {
  const { sessionId } = await params;
  const { courseId = "calc1" } = await searchParams;
  const isCalculusDemo = courseId === "calc1";
  const problem: WhiteboardProblem = {
    id: `${sessionId}-problem`,
    context: isCalculusDemo
      ? {
          prompt_text: "Differentiate y = (3x² + 1)⁴. Show each step.",
          solution_reference:
            "Accept 4(3x² + 1)³(6x) and 24x(3x² + 1)³ as complete, equivalent derivatives. Multiplying 4 and 6x is optional simplification.",
          topic: "derivatives",
          difficulty: "medium",
          expected_skills: ["calc1.derivatives.chain-rule"],
          source: "generated",
        }
      : {
          prompt_text: "Work through the current course problem on the whiteboard.",
          source: "manual",
        },
  };

  return (
    <main className="flex h-dvh flex-col bg-white">
      <header className="border-b border-slate-200 px-3 py-2 sm:px-5">
        <div className="min-w-0">
          <Link className="text-sm font-semibold text-blue-700" href="/">Mentora</Link>
          <p className="truncate text-sm text-slate-600">
            {courseId} · Whiteboard: {sessionId}
          </p>
        </div>
      </header>
      <section className="min-h-0 flex-1" aria-label="Whiteboard canvas">
        <Whiteboard courseId={courseId} problem={problem} sessionId={sessionId} />
      </section>
    </main>
  );
}
