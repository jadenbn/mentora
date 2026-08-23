import type { TutorRequest, TutorResponse } from "@/types/tutor";
import { messageForStatus } from "@/lib/api/errors";
import { validateTutorRequest } from "@/lib/tutor/requestValidation";

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
  validateTutorRequest(args.request);

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
