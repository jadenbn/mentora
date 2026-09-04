"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Whiteboard } from "@/features/whiteboard/Whiteboard";
import { getCourseById, getSpaceById, updateSpace } from "@/lib/api/api";
import type { Course, Space } from "@/types/domain";

export function SpaceWorkspace({ spaceId }: { spaceId: string }) {
  const [feedbackHost, setFeedbackHost] = useState<HTMLDivElement | null>(null);
  const [thinkingHost, setThinkingHost] = useState<HTMLDivElement | null>(null);
  const [space, setSpace] = useState<Space | null | undefined>(undefined);
  const [course, setCourse] = useState<Course | null>(null);

  useEffect(() => {
    let active = true;
    void getSpaceById(spaceId)
      .then((loaded) => {
        if (active) setSpace(loaded);
      })
      .catch(() => {
        if (active) setSpace(null);
      });
    return () => {
      active = false;
    };
  }, [spaceId]);

  useEffect(() => {
    if (!space) return;
    let active = true;
    void getCourseById(space.course_id)
      .then((loaded) => {
        if (active) setCourse(loaded);
      })
      .catch(() => {
        // The course name is a nice-to-have in the header; failing to load
        // it should not block the workspace.
      });
    return () => {
      active = false;
    };
  }, [space]);

  // undefined: still loading. null: fetched and not found.
  if (space === undefined) {
    return (
      <main className="grid h-dvh place-items-center text-sm text-slate-500">
        Opening space…
      </main>
    );
  }

  if (!space) {
    return (
      <main className="grid h-dvh place-items-center p-6 text-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-950">Space not found</h1>
          <p className="mt-2 text-slate-600">
            This space does not exist, or it may have been deleted.
          </p>
          <Link
            className="mt-6 inline-block rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white"
            href="/courses"
          >
            My courses
          </Link>
        </div>
      </main>
    );
  }

  function handleRename() {
    const next = prompt("Rename space", space!.title);
    const trimmed = next?.trim();
    if (!trimmed) return;
    void updateSpace(space!.course_id, space!.id, { title: trimmed })
      .then((updated) => setSpace(updated))
      .catch(() => {
        // A failed rename is surfaced by the title simply staying the same.
      });
  }

  return (
    <main className="relative h-dvh bg-white">
      <header className="pointer-events-none absolute inset-0 z-50 bg-transparent px-3 py-2 sm:px-5">
        <div className="mentora-workspace-info pointer-events-auto absolute bottom-4 left-3 min-w-0 sm:bottom-5 sm:left-5">
          <Link
            className="text-sm font-semibold text-blue-700"
            href={`/courses/${space.course_id}`}
          >
            ← {course?.name ?? "Course"}
          </Link>
          <p className="truncate text-sm text-slate-600">{space.title}</p>
          <button
            className="mt-1 inline-flex rounded-md border border-slate-200 bg-white/70 px-3 py-1.5 text-sm font-semibold text-slate-700 backdrop-blur-sm hover:cursor-grab hover:bg-white/90"
            onClick={handleRename}
            type="button"
          >
            Rename
          </button>
        </div>
        <div className="pointer-events-none absolute inset-x-0 top-14 px-3 sm:top-2 sm:px-52">
          <div ref={setFeedbackHost} />
          <div className="mt-1 flex justify-center" ref={setThinkingHost} />
        </div>
      </header>
      <section className="relative h-full min-h-0" aria-label="Whiteboard canvas">
        <Whiteboard
          courseId={space.course_id}
          feedbackHost={feedbackHost}
          thinkingHost={thinkingHost}
          problem={space.problem}
          spaceId={space.id}
        />
      </section>
    </main>
  );
}
