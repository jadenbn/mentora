import Link from "next/link";
import { SessionGrid } from "@/features/sessions/SessionGrid";

export default async function CoursePage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await params;

  return (
    <main className="mx-auto min-h-dvh max-w-6xl p-5 sm:p-8">
      <header className="flex flex-col gap-4 border-b border-slate-200 pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold tracking-[0.18em] text-blue-700">COURSE</p>
          <h1 className="mt-1 text-3xl font-bold text-slate-950">{courseId}</h1>
        </div>
        <Link
          className="rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white"
          href={{
            pathname: "/sessions/local-preview",
            query: { courseId },
          }}
        >
          Open whiteboard shell
        </Link>
      </header>
      <SessionGrid />
    </main>
  );
}
