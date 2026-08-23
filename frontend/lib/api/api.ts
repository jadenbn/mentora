import type { TutorRequest, TutorResponse } from "@/types/tutor";

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

/** Maps the backend's documented failure codes onto something a user can read. */
function messageForStatus(status: number, detail: unknown): string {
  switch (status) {
    case 413:
      return "The canvas image is too large to analyze.";
    case 415:
      return "The canvas image format is not supported.";
    case 422:
      return "The tutor request was rejected as invalid.";
    case 503: {
      const missing = (detail as { missing_settings?: string[] } | null)
        ?.missing_settings;
      return missing?.length
        ? `Tutor is not configured. Missing: ${missing.join(", ")}.`
        : "Tutor is not configured on the server.";
    }
    case 502:
      return "The tutor is temporarily unavailable.";
    case 504:
      return "The tutor took too long to respond.";
    default:
      return `Tutor request failed (${status}).`;
  }
}

/**
 * POST /api/tutor/analyze
 *
 * Multipart, per docs/TUTOR_AGENT.md: the TutorRequest travels as one JSON
 * string in `payload`, alongside the image files. Content-Type is deliberately
 * left unset so the browser supplies the multipart boundary.
 */
export async function analyzeCanvas(args: {
  request: TutorRequest;
  canvasImage: Blob;
  selectionImage?: Blob | null;
  signal?: AbortSignal;
}): Promise<TutorResponse> {
  const form = new FormData();
  form.append("payload", JSON.stringify(args.request));
  form.append("canvas_image", args.canvasImage, "canvas.png");
  if (args.selectionImage) {
    form.append("selection_image", args.selectionImage, "selection.png");
  }

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
