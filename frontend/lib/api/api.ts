import type { NormalizedBounds, TutorMode, TutorResponse } from "@/types/tutor";
import type { CourseDocument, DocumentType, Problem } from "@/types/domain";

/** The port the FastAPI backend listens on in development. */
const DEFAULT_API_PORT = 8000;

/**
 * Where the backend lives.
 *
 * Defaults to the same host the page was served from, on the backend's port.
 * That covers localhost and a phone or tablet hitting the dev server over the
 * network, where a hardcoded "localhost" would mean the tablet itself.
 *
 * Never falls back to same-origin: an empty base posts to the Next dev server
 * and 404s at :3000, which reads as a missing route rather than a config gap.
 */
export function apiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (configured) {
    return configured;
  }
  if (typeof window === "undefined") {
    return `http://localhost:${DEFAULT_API_PORT}`;
  }
  const { protocol, hostname } = window.location;
  return `${protocol}//${hostname}:${DEFAULT_API_PORT}`;
}

export class TutorApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = "TutorApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** Maps the backend's documented failures onto something a student can read. */
function messageForStatus(status: number, detail: unknown): string {
  switch (status) {
    case 400:
      return "There is nothing on the canvas to analyze.";
    case 413:
      return "The canvas image is too large to analyze.";
    case 415:
      return "That canvas image format is not supported.";
    case 422:
      return "The tutor request was rejected as invalid.";
    case 502:
      return "The tutor is temporarily unavailable.";
    case 503: {
      const missing = (detail as { missing_settings?: string[] } | null)?.missing_settings;
      return missing?.length
        ? `The tutor is not configured. Missing: ${missing.join(", ")}.`
        : "The tutor is not configured on the server.";
    }
    case 504:
      return "The tutor took too long to respond.";
    default:
      return `The tutor request failed (${status}).`;
  }
}

/**
 * POST /api/tutor/analyze
 *
 * Multipart. Content-Type is deliberately left unset so the browser supplies
 * the multipart boundary; setting it by hand omits the boundary and the
 * server cannot parse the body.
 */
export async function analyzeCanvas(args: {
  courseId: string;
  mode: TutorMode;
  canvasImage: Blob;
  priorAnnotations: NormalizedBounds[];
  problem?: Problem;
  signal?: AbortSignal;
}): Promise<TutorResponse> {
  const form = new FormData();
  form.append("course_id", args.courseId);
  form.append("mode", args.mode);
  form.append("canvas_image", args.canvasImage, "canvas.png");
  form.append("prior_annotations", JSON.stringify(args.priorAnnotations));
  if (args.problem) {
    form.append(
      "problem_context",
      JSON.stringify({
        id: args.problem.id,
        course_id: args.problem.courseId,
        document_id: args.problem.documentId,
        source: args.problem.source,
        prompt: args.problem.prompt,
      }),
    );
  }

  const response = await fetch(`${apiBaseUrl()}/api/tutor/analyze`, {
    method: "POST",
    body: form,
    signal: args.signal,
  });

  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = (await response.json())?.detail ?? null;
    } catch {
      // Non-JSON error body; the status alone has to carry the meaning.
    }
    throw new TutorApiError(
      messageForStatus(response.status, detail),
      response.status,
      detail,
    );
  }

  return response.json();
}

async function courseResponse<T>(response: Response, action: string): Promise<T> {
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = (await response.json())?.detail ?? null;
    } catch {
      // The fixed fallback below is safer than exposing an HTML/provider body.
    }
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray((detail as { missing_settings?: unknown } | null)?.missing_settings)
          ? `${action} is not configured. Missing: ${(detail as { missing_settings: string[] }).missing_settings.join(", ")}.`
          : `${action} failed (${response.status}).`;
    throw new TutorApiError(message, response.status, detail);
  }
  return response.json() as Promise<T>;
}

export async function listCourseDocuments(courseId: string): Promise<CourseDocument[]> {
  const response = await fetch(`${apiBaseUrl()}/api/courses/${courseId}/documents`);
  return courseResponse<CourseDocument[]>(response, "Loading course materials");
}

export async function uploadCourseDocument(args: {
  courseId: string;
  file: File;
  documentType: DocumentType;
}): Promise<CourseDocument> {
  const form = new FormData();
  form.append("file", args.file);
  form.append("document_type", args.documentType);
  const response = await fetch(
    `${apiBaseUrl()}/api/courses/${args.courseId}/documents`,
    { method: "POST", body: form },
  );
  return courseResponse<CourseDocument>(response, "Uploading the document");
}

interface ProblemResponse {
  id: string;
  course_id: string;
  document_id: string;
  source: "generated";
  prompt: string;
}

interface AttributedSkillResponse {
  id: string;
  name: string;
  difficulty_band: number;
}

interface GeneratedProblemResponse {
  problem: ProblemResponse;
  skills: AttributedSkillResponse[];
}

/**
 * POST /api/courses/{course_id}/questions/generate
 *
 * questionRequest may be empty: the engine then picks a topic itself (an
 * implicit "practice next topic") instead of grounding the student's own
 * description. Either way the server attributes the generated problem to
 * the topic(s) it exercises -- existing or newly identified from the
 * question itself -- and returns the primary one so marking this problem
 * correct can record an attempt.
 */
export async function generateCourseQuestion(
  courseId: string,
  studentId: string,
  documentId: string,
  questionRequest: string,
): Promise<Problem> {
  const response = await fetch(
    `${apiBaseUrl()}/api/courses/${courseId}/questions/generate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        student_id: studentId,
        document_id: documentId,
        question_request: questionRequest.trim(),
      }),
    },
  );
  const data = await courseResponse<GeneratedProblemResponse>(
    response,
    "Generating a question",
  );
  const primary = data.skills[0];
  return {
    id: data.problem.id,
    courseId: data.problem.course_id,
    documentId: data.problem.document_id,
    source: data.problem.source,
    prompt: data.problem.prompt,
    skill: primary ? { skillId: primary.id, skillName: primary.name } : undefined,
  };
}

export interface AttemptOutcome {
  attemptId: string;
  updatedSkills: Record<string, number>;
}

/**
 * POST /api/courses/{course_id}/work
 *
 * Submit the canvas for a graded check-in. The tutor's own reading of the
 * work decides the outcome and the server records the attempt in the same
 * round trip; the difficulty comes from what selection asked for at
 * generation time. Nothing the browser sends scores the student's work — it
 * used to send `correct`, which meant anyone could set their own mastery.
 *
 * `attempt` comes back null when nothing was recorded: a hint rather than a
 * mark, a canvas the tutor could not read, or a problem already attempted.
 */
export async function submitWork(args: {
  courseId: string;
  studentId: string;
  sessionId: string;
  problemId: string;
  mode: TutorMode;
  canvasImage: Blob;
  priorAnnotations: NormalizedBounds[];
  hintsUsed: number;
  signal?: AbortSignal;
}): Promise<{ tutor: TutorResponse; attempt: AttemptOutcome | null }> {
  const form = new FormData();
  form.append("session_id", args.sessionId);
  form.append("mode", args.mode);
  form.append("problem_id", args.problemId);
  form.append("hints_used", String(args.hintsUsed));
  form.append("canvas_image", args.canvasImage, "canvas.png");
  form.append("prior_annotations", JSON.stringify(args.priorAnnotations));

  const url =
    `${apiBaseUrl()}/api/courses/${args.courseId}/work` +
    `?student_id=${encodeURIComponent(args.studentId)}`;
  const response = await fetch(url, { method: "POST", body: form, signal: args.signal });

  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = (await response.json())?.detail ?? null;
    } catch {
      // Non-JSON error body; the status alone has to carry the meaning.
    }
    throw new TutorApiError(
      messageForStatus(response.status, detail),
      response.status,
      detail,
    );
  }

  const data = (await response.json()) as {
    tutor: TutorResponse;
    attempt: { attempt_id: string; updated_skills: Record<string, number> } | null;
  };
  return {
    tutor: data.tutor,
    attempt: data.attempt
      ? { attemptId: data.attempt.attempt_id, updatedSkills: data.attempt.updated_skills }
      : null,
  };
}
