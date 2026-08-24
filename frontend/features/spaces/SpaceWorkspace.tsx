"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";
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
    <main className="flex h-dvh flex-col bg-[#f5f2e9] text-[#202620]">
      <header className="flex min-h-16 items-center justify-between gap-3 border-b border-[#d9d6cc] bg-[#fffdf8] px-3 py-2 sm:px-5">
        <div className="flex min-w-0 items-center gap-3">
          <div
            aria-hidden="true"
            className="grid size-10 shrink-0 place-items-center rounded-xl bg-[#607d6c] font-serif text-xl font-bold text-white shadow-sm"
          >
            M
          </div>
          <div className="min-w-0">
            <Link
              className="text-xs font-bold uppercase tracking-[0.13em] text-[#607d6c] hover:text-[#405f4d]"
              href={`/courses/${space.courseId}`}
            >
              ← {course?.name ?? "Course"}
            </Link>
            <p className="truncate text-sm font-semibold text-[#404940]">{space.title}</p>
          </div>
        </div>
        <button
          className="shrink-0 rounded-lg border border-[#d9d6cc] bg-white px-3 py-1.5 text-sm font-semibold text-[#536057] hover:bg-[#f5f2e9]"
          onClick={handleRename}
          type="button"
        >
          Rename
        </button>
      </header>
      <section className="min-h-0 flex-1" aria-label="Whiteboard canvas">
        <Whiteboard courseId={space.courseId} problem={space.problem} spaceId={space.id} />
      </section>
    </main>
  );
}
