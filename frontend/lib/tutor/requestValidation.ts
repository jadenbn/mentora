import type { TutorRequest } from "@/types/tutor";

const MAX_IMAGE_DIMENSION = 16_384;

export class TutorRequestValidationError extends Error {
  readonly detail: { field: string; value: unknown };

  constructor(field: string, value: unknown) {
    super(`The tutor request has an invalid ${field}. Please recapture the canvas and try again.`);
    this.name = "TutorRequestValidationError";
    this.detail = { field, value };
  }
}

function requireImageDimension(field: string, value: number): void {
  if (
    !Number.isSafeInteger(value) ||
    value <= 0 ||
    value > MAX_IMAGE_DIMENSION
  ) {
    throw new TutorRequestValidationError(field, value);
  }
}

/** Guard the dimensions most likely to turn an otherwise valid upload into a 422. */
export function validateTutorRequest(request: TutorRequest): void {
  requireImageDimension("canvas.image_width", request.canvas.image_width);
  requireImageDimension("canvas.image_height", request.canvas.image_height);
}
