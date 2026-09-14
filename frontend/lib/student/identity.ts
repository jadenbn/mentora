/**
 * A stable anonymous student id, local to this browser.
 *
 * The app has no auth (matches the backend's posture — see
 * app/config.py's api_key docstring), so "student" here means "this browser
 * profile." The id is minted once and persisted; every browser is a distinct
 * student, so two people on the same deployment never share a model.
 *
 * To inspect this browser's student on the dev dashboard, paste
 * localStorage["mentora:student-id"] into its student field. Clear the key
 * to start over as a fresh student.
 */

const STORAGE_KEY = "mentora:student-id";

/** Held for the page's lifetime when storage is unavailable, so one visit
 * is still one student rather than a new one per request. */
let inMemoryId: string | null = null;

function mintStudentId(): string {
  const random = globalThis.crypto?.randomUUID
    ? globalThis.crypto.randomUUID().replace(/-/g, "")
    : `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  return `student_${random}`;
}

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** Stable per-browser id, minted on first use. */
export function getStudentId(): string {
  const store = storage();
  if (store) {
    try {
      const existing = store.getItem(STORAGE_KEY);
      if (existing) {
        return existing;
      }
      const minted = mintStudentId();
      store.setItem(STORAGE_KEY, minted);
      return minted;
    } catch {
      // Storage present but unusable (private mode, quota): fall through.
    }
  }
  inMemoryId ??= mintStudentId();
  return inMemoryId;
}
