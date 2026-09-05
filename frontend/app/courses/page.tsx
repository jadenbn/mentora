"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { createCourse, listCourses } from "@/lib/api/api";
import type { Course } from "@/types/domain";

export default function CoursesPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void listCourses()
      .then((loaded) => {
        if (active) setCourses(loaded);
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Could not load courses.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const name = String(data.get("course-name") ?? "").trim();
    const description = String(data.get("course-description") ?? "").trim();
    if (!name || creating) return;

    setCreating(true);
    setError(null);
    try {
      const created = await createCourse({ name, description });
      setCourses((current) => [created, ...current]);
      form.reset();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create the course.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <main className="mx-auto min-h-dvh max-w-4xl p-5 sm:p-8">
      <header className="border-b border-slate-200 pb-6">
        <Link className="text-sm font-semibold text-blue-700" href="/">
          Mentora
        </Link>
        <h1 className="mt-1 text-3xl font-bold text-slate-950">My courses</h1>
      </header>

      <form
        className="mt-6 flex flex-col gap-2 rounded-lg border border-slate-200 bg-white p-4 sm:flex-row sm:items-end"
        onSubmit={handleCreate}
      >
        <div className="flex-1">
          <label className="block text-xs font-semibold text-slate-600" htmlFor="course-name">
            Name
          </label>
          <input
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            id="course-name"
            maxLength={200}
            name="course-name"
            placeholder="e.g. MATH 101"
            required
            type="text"
          />
        </div>
        <div className="flex-1">
          <label
            className="block text-xs font-semibold text-slate-600"
            htmlFor="course-description"
          >
            Description
          </label>
          <input
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            id="course-description"
            maxLength={2000}
            name="course-description"
            placeholder="What is this course about?"
            type="text"
          />
        </div>
        <button
          className="shrink-0 rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800 disabled:bg-slate-400"
          disabled={creating}
          type="submit"
        >
          {creating ? "Creating…" : "Create course"}
        </button>
      </form>

      {error ? (
        <p className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      ) : null}

      {loading ? (
        <p className="mt-6 text-sm text-slate-500">Loading courses…</p>
      ) : courses.length === 0 ? (
        <div className="mt-6 rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-slate-600">
          No courses yet. Create one to get started.
        </div>
      ) : (
        <ul className="mt-6 grid gap-4 sm:grid-cols-2">
          {courses.map((course) => (
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
      )}
    </main>
  );
}
