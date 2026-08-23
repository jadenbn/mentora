import Link from "next/link";
import { notFound } from "next/navigation";
import { SpaceGrid } from "@/features/spaces/SpaceGrid";
import { getCourse } from "@/lib/spaces/courses";

export default async function CoursePage({
  params,
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  const course = getCourse(courseId);

  if (!course) {
    notFound();
  }

  return (
    <main className="mx-auto min-h-dvh max-w-6xl p-5 sm:p-8">
      <header className="border-b border-slate-200 pb-6">
        <Link className="text-sm font-semibold text-blue-700" href="/courses">
          ← My courses
        </Link>
        <h1 className="mt-1 text-3xl font-bold text-slate-950">{course.name}</h1>
        <p className="mt-1 text-slate-600">{course.description}</p>
      </header>
      <SpaceGrid courseId={course.id} />
    </main>
  );
}
