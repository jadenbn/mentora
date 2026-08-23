import Link from "next/link";
import { COURSES } from "@/lib/spaces/courses";

export default function CoursesPage() {
  return (
    <main className="mx-auto min-h-dvh max-w-4xl p-5 sm:p-8">
      <header className="border-b border-slate-200 pb-6">
        <Link className="text-sm font-semibold text-blue-700" href="/">
          Mentora
        </Link>
        <h1 className="mt-1 text-3xl font-bold text-slate-950">My courses</h1>
      </header>

      <ul className="mt-6 grid gap-4 sm:grid-cols-2">
        {COURSES.map((course) => (
          <li key={course.id}>
            <Link
              className="block h-full rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-400 hover:shadow-sm"
              href={`/courses/${course.id}`}
            >
              <p className="text-lg font-bold text-slate-950">{course.name}</p>
              <p className="mt-1 text-sm text-slate-600">{course.description}</p>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
