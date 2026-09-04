/**
 * Canvas persistence (ARCHITECTURE.md sections 8, 28, 29).
 *
 * One localStorage entry per session, holding a versioned envelope around a
 * tldraw store snapshot. Autosave is debounced so a burst of pen strokes costs
 * one write rather than one per point.
 *
 * Every storage access is guarded. Safari private mode throws on write, quota
 * exhaustion throws on write, and stored data can be corrupt or written by a
 * newer build. None of that may break the canvas, so the failure mode is
 * always "no persistence", never an exception reaching the caller.
 */

import { getSnapshot, loadSnapshot } from "tldraw";
import type { Editor } from "tldraw";

/** Bump when the stored shape changes; older envelopes are then ignored. */
export const SNAPSHOT_VERSION = 1;

/** Long enough to coalesce a stroke, short enough to survive a tab close. */
const DEFAULT_DEBOUNCE_MS = 1_000;

const KEY_PREFIX = "mentora:session:";

export interface StoredSnapshot {
  version: number;
  updatedAt: string;
  snapshot: unknown;
}

/** Namespaced localStorage key for one session's canvas. */
export function sessionStorageKey(sessionId: string): string {
  return `${KEY_PREFIX}${sessionId}`;
}

/**
 * Reading `window.localStorage` can itself throw when site data is blocked,
 * so even acquiring the object needs a guard.
 */
function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** Serialize the current document. Returns false if storage was unavailable. */
export function saveCanvas(editor: Editor, sessionId: string): boolean {
  const store = storage();
  if (!store) {
    return false;
  }

  try {
    const envelope: StoredSnapshot = {
      version: SNAPSHOT_VERSION,
      updatedAt: new Date().toISOString(),
      snapshot: getSnapshot(editor.store),
    };
    store.setItem(sessionStorageKey(sessionId), JSON.stringify(envelope));
    return true;
  } catch {
    // Quota exceeded, private mode, or a snapshot that will not serialize.
    return false;
  }
}

/** Restore a stored document. Returns false when there is nothing usable. */
export function loadCanvas(editor: Editor, sessionId: string): boolean {
  const store = storage();
  if (!store) {
    return false;
  }

  let envelope: StoredSnapshot;
  try {
    const raw = store.getItem(sessionStorageKey(sessionId));
    if (!raw) {
      return false;
    }
    envelope = JSON.parse(raw) as StoredSnapshot;
  } catch {
    return false;
  }

  // A snapshot from a different format is ignored rather than restored as
  // garbage. Leaving the canvas untouched beats corrupting it.
  if (!envelope || envelope.version !== SNAPSHOT_VERSION) {
    return false;
  }
  if (envelope.snapshot === null || envelope.snapshot === undefined) {
    return false;
  }

  return loadCanvasSnapshot(editor, envelope.snapshot);
}

/** Restore an in-memory tldraw snapshot without changing session storage. */
export function loadCanvasSnapshot(editor: Editor, snapshot: unknown): boolean {
  try {
    loadSnapshot(editor.store, snapshot as never);
    return true;
  } catch {
    return false;
  }
}

/** Forget one session's stored canvas. */
export function clearCanvas(sessionId: string): void {
  try {
    storage()?.removeItem(sessionStorageKey(sessionId));
  } catch {
    // Nothing to do: the goal was for it to be gone.
  }
}

/** Persist on change, debounced. Returns a dispose function. */
export function startAutosave(
  editor: Editor,
  sessionId: string,
  options: { debounceMs?: number; onSave?: () => void } = {},
): () => void {
  const debounceMs = options.debounceMs ?? DEFAULT_DEBOUNCE_MS;

  let timer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  const unlisten = editor.store.listen(() => {
    if (disposed) {
      return;
    }
    // Trailing edge: restart the clock on every change so only the settle
    // writes. A failed write is swallowed by saveCanvas, leaving the
    // subscription intact for the next change.
    if (timer !== null) {
      clearTimeout(timer);
    }
    timer = setTimeout(() => {
      timer = null;
      if (saveCanvas(editor, sessionId)) {
        options.onSave?.();
      }
    }, debounceMs);
  });

  return () => {
    disposed = true;
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    unlisten();
  };
}
