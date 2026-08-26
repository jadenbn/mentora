"use client";

import Link from "next/link";
import { useState, useSyncExternalStore } from "react";
import { Whiteboard } from "@/features/whiteboard/Whiteboard";
import { getCourse } from "@/lib/spaces/courses";
import {
  getServerSpacesSnapshot,
  getSpacesSnapshot,
  renameSpace,
  subscribeToSpaces,
} from "@/lib/spaces/store";
import { useIsClient } from "@/lib/useIsClient";

export function SpaceWorkspace({ spaceId }: { spaceId: string }) {
  const hydrated = useIsClient();
  const [feedbackHost, setFeedbackHost] = useState<HTMLDivElement | null>(null);
  // Read the index directly so a rename elsewhere is reflected here.
  const all = useSyncExternalStore(
    subscribeToSpaces,
    getSpacesSnapshot,
    getServerSpacesSnapshot,
  );
  const space = all.find((candidate) => candidate.id === spaceId);

  if (!hydrated) {
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
            This space does not exist on this device. Spaces are stored locally
            for now, so they do not follow you between browsers.
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

  const course = getCourse(space.courseId);

  function handleRename() {
    const next = prompt("Rename space", space!.title);
    if (next && next.trim()) {
      renameSpace(space!.id, next);
    }
  }

  return (
    <main className="relative h-dvh bg-white">
      <header className="pointer-events-none absolute inset-x-0 top-0 z-50 flex flex-wrap items-center justify-between gap-3 bg-transparent px-3 py-2 sm:px-5">
        <div className="pointer-events-auto min-w-0">
          <Link
            className="text-sm font-semibold text-blue-700"
            href={`/courses/${space.courseId}`}
          >
            ← {course?.name ?? "Course"}
          </Link>
          <p className="truncate text-sm text-slate-600">{space.title}</p>
        </div>
        <div
          className="pointer-events-auto min-w-0 flex-1 basis-full sm:basis-auto"
          ref={setFeedbackHost}
        />
        <button
          className="pointer-events-auto shrink-0 rounded-md border border-slate-200 bg-white/70 px-3 py-1.5 text-sm font-semibold text-slate-700 backdrop-blur-sm hover:bg-white/90"
          onClick={handleRename}
          type="button"
        >
          Rename
        </button>
      </header>
      <section className="relative h-full min-h-0" aria-label="Whiteboard canvas">
        <Whiteboard
          courseId={space.courseId}
          feedbackHost={feedbackHost}
          problem={space.problem}
          spaceId={space.id}
        />
      </section>
    </main>
  );
}
