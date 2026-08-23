import type { NormalizedBounds, TutorMode, TutorResponse } from "@/types/tutor";

export const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

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
  signal?: AbortSignal;
}): Promise<TutorResponse> {
  const form = new FormData();
  form.append("course_id", args.courseId);
  form.append("mode", args.mode);
  form.append("canvas_image", args.canvasImage, "canvas.png");
  form.append("prior_annotations", JSON.stringify(args.priorAnnotations));

  const response = await fetch(`${apiBaseUrl}/api/tutor/analyze`, {
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
