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
import type { WhiteboardProblem } from "@/features/whiteboard/Whiteboard";

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
  const problem: WhiteboardProblem = {
    id: `${space.id}-problem`,
    context:
      space.courseId === "calc1"
        ? {
            prompt_text: "Differentiate y = (3x² + 1)⁴. Show each step.",
            solution_reference:
              "Accept 4(3x² + 1)³(6x) and 24x(3x² + 1)³ as complete, equivalent derivatives.",
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

  function handleRename() {
    const next = prompt("Rename space", space!.title);
    if (next && next.trim()) {
      renameSpace(space!.id, next);
    }
  }

  return (
    <main className="flex h-dvh flex-col bg-white">
      <header className="flex items-center justify-between gap-3 border-b border-slate-200 px-3 py-2 sm:px-5">
        <div className="min-w-0">
          <Link
            className="text-sm font-semibold text-blue-700"
            href={`/courses/${space.courseId}`}
          >
            ← {course?.name ?? "Course"}
          </Link>
          <p className="truncate text-sm text-slate-600">{space.title}</p>
        </div>
        <button
          className="shrink-0 rounded-md border border-slate-200 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          onClick={handleRename}
          type="button"
        >
          Rename
        </button>
      </header>
      <section className="min-h-0 flex-1" aria-label="Whiteboard canvas">
        <Whiteboard
          courseId={space.courseId}
          problem={problem}
          sessionId={space.id}
        />
      </section>
    </main>
  );
}
