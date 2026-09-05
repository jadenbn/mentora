"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearCanvas } from "@/lib/canvas/persistence";
import { createSpace, deleteSpaceById, listSpaces } from "@/lib/api/api";
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

export function SpaceGrid({ courseId }: { courseId: string }) {
  const router = useRouter();
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void listSpaces(courseId)
      .then((loaded) => {
        if (active) setSpaces(loaded);
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Could not load spaces.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [courseId]);

  async function handleCreate() {
    try {
      const space = await createSpace(courseId);
      router.push(`/spaces/${space.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create a Space.");
    }
  }

  async function handleDelete(space: Space) {
    if (!confirm(`Delete "${space.title}" and its canvas? This cannot be undone.`)) {
      return;
    }
    try {
      await deleteSpaceById(courseId, space.id);
      clearCanvas(space.id);
      setSpaces((current) => current.filter((item) => item.id !== space.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not delete this Space.");
    }
  }

  return (
    <section className="py-8" aria-labelledby="spaces-heading">
      <div className="flex items-center justify-between">
        <h2 id="spaces-heading" className="text-xl font-bold text-slate-950">
          Spaces
        </h2>
        <button
          className="rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white hover:bg-blue-800"
          onClick={() => void handleCreate()}
          type="button"
        >
          New space
        </button>
      </div>

      {error ? (
        <p className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      ) : null}

      {loading ? (
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
                  Last worked on {formatUpdated(space.updated_at)}
                </p>
              </Link>
              <button
                className="mt-3 text-xs font-semibold text-slate-500 hover:text-red-700"
                onClick={() => void handleDelete(space)}
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
