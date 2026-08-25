/**
 * A stable anonymous student id, local to this browser.
 *
 * The app has no auth (matches the backend's posture — see
 * app/config.py's cors_allow_origins docstring), so "student" here means
 * "this browser profile." Generated once and persisted, the same pattern
 * lib/spaces/store.ts uses for space ids.
 */

const STORAGE_KEY = "mentora:student-id";

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

function newId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `student_${Date.now().toString(36)}`;
  }
}

/** Stable per-browser id. Falls back to a fresh one each call if storage is unavailable. */
export function getStudentId(): string {
  const store = storage();
  if (!store) {
    return newId();
  }
  try {
    const existing = store.getItem(STORAGE_KEY);
    if (existing) {
      return existing;
    }
    const created = newId();
    store.setItem(STORAGE_KEY, created);
    return created;
  } catch {
    return newId();
  }
}
