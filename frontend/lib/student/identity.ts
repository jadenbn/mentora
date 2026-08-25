/**
 * A stable anonymous student id, local to this browser.
 *
 * The app has no auth (matches the backend's posture — see
 * app/config.py's cors_allow_origins docstring), so "student" here means
 * "this browser profile."
 *
 * Defaults to the literal "dev-student" — the same default the dev
 * dashboard's student field already uses (backend/app/api/dev.py). The app
 * runs on a different origin than the backend-served dashboard, so
 * localStorage can't be shared between them directly; matching the two
 * defaults means completing a problem in the app and then opening
 * /dev/dashboard shows the same student's mastery with no manual steps,
 * instead of the dashboard silently looking at a different (empty) student's
 * data because the app picked a random id. Still persisted and still
 * override-able — clear or edit localStorage["mentora:student-id"] for a
 * distinct identity when deliberately testing multiple students.
 */

const STORAGE_KEY = "mentora:student-id";
const DEFAULT_STUDENT_ID = "dev-student";

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** Stable per-browser id. Falls back to the shared default if storage is unavailable. */
export function getStudentId(): string {
  const store = storage();
  if (!store) {
    return DEFAULT_STUDENT_ID;
  }
  try {
    const existing = store.getItem(STORAGE_KEY);
    if (existing) {
      return existing;
    }
    store.setItem(STORAGE_KEY, DEFAULT_STUDENT_ID);
    return DEFAULT_STUDENT_ID;
  } catch {
    return DEFAULT_STUDENT_ID;
  }
}
