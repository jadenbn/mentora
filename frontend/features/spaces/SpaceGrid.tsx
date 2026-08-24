"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useSyncExternalStore } from "react";
import { useIsClient } from "@/lib/useIsClient";
import {
  createSpace,
  deleteSpace,
  getServerSpacesSnapshot,
  getSpacesSnapshot,
  subscribeToSpaces,
} from "@/lib/spaces/store";
import type { Space } from "@/types/domain";

function formatUpdated(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) {
    return "unknown";
  }
  return when.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function SpaceGrid({ roomId }: { roomId: string }) {
  const router = useRouter();
  const hydrated = useIsClient();
  // localStorage is an external store, so it is read through
  // useSyncExternalStore rather than mirrored into state by an effect.
  const all = useSyncExternalStore(
    subscribeToSpaces,
    getSpacesSnapshot,
    getServerSpacesSnapshot,
  );

  const spaces = useMemo(
    () =>
      all
        .filter((space) => space.roomId === roomId)
        .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
    [all, roomId],
  );

  function handleCreate() {
    const space = createSpace(roomId);
    router.push(`/spaces/${space.id}`);
  }

  function handleDelete(space: Space) {
    if (!confirm(`Delete "${space.title}" and its canvas? This cannot be undone.`)) {
      return;
    }
    deleteSpace(space.id);
  }

  return (
    <section className="py-8" aria-labelledby="spaces-heading">
      <div className="flex items-center justify-between">
        <h2 id="spaces-heading" className="text-xl font-bold text-slate-950">
          Spaces
        </h2>
        <button
          className="rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white hover:bg-blue-800"
          onClick={handleCreate}
          type="button"
        >
          New space
        </button>
      </div>

      {!hydrated ? (
        <p className="mt-4 text-sm text-slate-500">Loading spaces…</p>
      ) : spaces.length === 0 ? (
        <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-slate-600">
          No spaces yet. Create one to start working.
        </div>
      ) : (
        <ul className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {spaces.map((space) => (
            <li
              key={space.id}
              className="rounded-xl border border-slate-200 bg-white p-4 transition hover:border-blue-400 hover:shadow-sm"
            >
              <Link className="block" href={`/spaces/${space.id}`}>
                <p className="font-semibold text-slate-950">{space.title}</p>
                <p className="mt-1 text-xs text-slate-500">
                  Last worked on {formatUpdated(space.updatedAt)}
                </p>
              </Link>
              <button
                className="mt-3 text-xs font-semibold text-slate-500 hover:text-red-700"
                onClick={() => handleDelete(space)}
                type="button"
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
