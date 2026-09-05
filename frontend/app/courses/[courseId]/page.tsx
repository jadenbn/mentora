import Link from "next/link";
import { notFound } from "next/navigation";
import { SpaceGrid } from "@/features/spaces/SpaceGrid";
import { CourseMaterials } from "@/features/materials/CourseMaterials";
import { DeleteCourseButton } from "@/features/courses/DeleteCourseButton";
import { getCourseById } from "@/lib/api/api";

export default async function CoursePage({
  params,
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  const course = await getCourseById(courseId);

  if (!course) {
    notFound();
  }

  return (
    <main className="mx-auto min-h-dvh max-w-6xl p-5 sm:p-8">
      <header className="border-b border-slate-200 pb-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <Link className="text-sm font-semibold text-blue-700" href="/courses">
              ← My courses
            </Link>
            <h1 className="mt-1 text-3xl font-bold text-slate-950">{course.name}</h1>
            <p className="mt-1 text-slate-600">{course.description}</p>
          </div>
          <DeleteCourseButton courseId={course.id} courseName={course.name} />
        </div>
      </header>
      <CourseMaterials courseId={course.id} />
      <SpaceGrid courseId={course.id} />
    </main>
  );
}
