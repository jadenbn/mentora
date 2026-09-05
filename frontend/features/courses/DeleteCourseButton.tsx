"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { deleteCourseById } from "@/lib/api/api";

export function DeleteCourseButton({
  courseId,
  courseName,
}: {
  courseId: string;
  courseName: string;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  async function handleDelete() {
    if (!confirm(`Delete "${courseName}" and all of its spaces? This cannot be undone.`)) {
      return;
    }
    try {
      await deleteCourseById(courseId);
      router.push("/courses");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not delete the course.");
    }
  }

  return (
    <>
      <button
        className="text-sm font-semibold text-slate-500 hover:text-red-700"
        onClick={() => void handleDelete()}
        type="button"
      >
        Delete course
      </button>
      {error ? <p className="mt-2 text-sm text-red-800">{error}</p> : null}
    </>
  );
}
