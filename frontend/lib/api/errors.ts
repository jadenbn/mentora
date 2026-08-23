interface ValidationIssue {
  loc?: unknown;
}

function validationField(detail: unknown): string | null {
  if (!Array.isArray(detail) || detail.length === 0) {
    return null;
  }
  const location = (detail[0] as ValidationIssue | null)?.loc;
  if (!Array.isArray(location)) {
    return null;
  }
  const safeParts = location
    .filter((part) => part !== "body" && part !== "payload")
    .filter(
      (part): part is string | number =>
        (typeof part === "string" && /^[a-zA-Z0-9_]+$/.test(part)) ||
        (typeof part === "number" && Number.isSafeInteger(part) && part >= 0),
    );
  return safeParts.length > 0 ? safeParts.join(".") : null;
}

/** Maps the backend's documented failure codes onto something a user can read. */
export function messageForStatus(status: number, detail: unknown): string {
  switch (status) {
    case 413:
      return "The canvas image is too large to analyze.";
    case 415:
      return "The canvas image format is not supported.";
    case 422: {
      const field = validationField(detail);
      return field
        ? `The tutor request has an invalid ${field}. Please refresh the canvas and try again.`
        : "The tutor request is invalid. Please refresh the canvas and try again.";
    }
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
