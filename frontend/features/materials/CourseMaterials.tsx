"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import {
  createSpace,
  generateCourseQuestion,
  listCourseDocuments,
  uploadCourseDocument,
} from "@/lib/api/api";
import type { CourseDocument, DocumentType } from "@/types/domain";

const DOCUMENT_TYPES: { value: DocumentType; label: string }[] = [
  { value: "lecture", label: "Lecture" },
  { value: "assignment", label: "Assignment" },
  { value: "exam", label: "Exam" },
  { value: "practice_exam", label: "Practice exam" },
  { value: "syllabus", label: "Syllabus" },
  { value: "formula_sheet", label: "Formula sheet" },
  { value: "other", label: "Other" },
];

function withoutExtension(filename: string): string {
  return filename.replace(/\.[^.]+$/, "") || filename;
}

export function CourseMaterials({ courseId }: { courseId: string }) {
  const router = useRouter();
  const [documents, setDocuments] = useState<CourseDocument[]>([]);
  const [documentType, setDocumentType] = useState<DocumentType>("lecture");
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [questionRequests, setQuestionRequests] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void listCourseDocuments(courseId)
      .then((loaded) => {
        if (active) setDocuments(loaded);
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Could not load materials.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [courseId]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem("course-document") as HTMLInputElement | null;
    const file = input?.files?.[0];
    if (!file || uploading) return;

    setUploading(true);
    setError(null);
    try {
      const uploaded = await uploadCourseDocument({ courseId, file, documentType });
      setDocuments((current) => [
        uploaded,
        ...current.filter((item) => item.document_id !== uploaded.document_id),
      ]);
      form.reset();
      setDocumentType("lecture");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function handleGenerate(document: CourseDocument) {
    if (generatingId) return;
    const questionRequest = questionRequests[document.document_id]?.trim() ?? "";
    if (!questionRequest) {
      setError("Describe the kind of question you want generated.");
      return;
    }
    setGeneratingId(document.document_id);
    setError(null);
    try {
      const problem = await generateCourseQuestion(
        courseId,
        document.document_id,
        questionRequest,
      );
      const space = await createSpace(courseId, {
        title: `Practice — ${withoutExtension(document.filename)}`,
        problem_id: problem.id,
      });
      router.push(`/spaces/${space.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Question generation failed.");
      setGeneratingId(null);
    }
  }

  return (
    <section className="border-b border-slate-200 py-8" aria-labelledby="materials-heading">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 id="materials-heading" className="text-xl font-bold text-slate-950">
            Course materials
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            Upload notes or assessments, then generate a grounded practice question.
          </p>
        </div>
        <form className="flex flex-col gap-2 sm:flex-row" onSubmit={handleUpload}>
          <select
            aria-label="Document type"
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            onChange={(event) => setDocumentType(event.target.value as DocumentType)}
            value={documentType}
          >
            {DOCUMENT_TYPES.map((type) => (
              <option key={type.value} value={type.value}>{type.label}</option>
            ))}
          </select>
          <input
            accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
            className="max-w-64 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            name="course-document"
            required
            type="file"
          />
          <button
            className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800 disabled:bg-slate-400"
            disabled={uploading}
            type="submit"
          >
            {uploading ? "Uploading…" : "Upload"}
          </button>
        </form>
      </div>

      {error ? (
        <p className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      ) : null}

      {loading ? (
        <p className="mt-4 text-sm text-slate-500">Loading materials…</p>
      ) : documents.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500">No course materials uploaded yet.</p>
      ) : (
        <ul className="mt-5 grid gap-3 sm:grid-cols-2">
          {documents.map((document) => (
            <li
              className="rounded-xl border border-slate-200 bg-white p-4"
              key={document.document_id}
            >
              <div className="min-w-0">
                <p className="truncate font-semibold text-slate-950">{document.filename}</p>
                <p className="mt-1 text-xs capitalize text-slate-500">
                  {document.document_type.replace("_", " ")} · {document.total_pages} page
                  {document.total_pages === 1 ? "" : "s"}
                </p>
              </div>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <input
                  aria-label={`Question request for ${document.filename}`}
                  className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  maxLength={1000}
                  onChange={(event) =>
                    setQuestionRequests((current) => ({
                      ...current,
                      [document.document_id]: event.target.value,
                    }))
                  }
                  placeholder="e.g. A difficult conceptual chain-rule question"
                  type="text"
                  value={questionRequests[document.document_id] ?? ""}
                />
                <button
                  className="shrink-0 rounded-lg border border-blue-200 px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50 disabled:text-slate-400"
                  disabled={
                    generatingId !== null ||
                    !(questionRequests[document.document_id]?.trim())
                  }
                  onClick={() => void handleGenerate(document)}
                  type="button"
                >
                  {generatingId === document.document_id ? "Generating…" : "Generate question"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
