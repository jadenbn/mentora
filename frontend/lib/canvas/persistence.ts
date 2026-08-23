/**
 * Canvas persistence (ARCHITECTURE.md sections 8, 28, 29).
 *
 * NOT IMPLEMENTED YET. These signatures exist so tests/persistence.test.ts
 * reads as an executable specification: every test currently fails, and each
 * failure names one behaviour still to build.
 *
 * Intended design:
 *   - one localStorage entry per session, under a namespaced key
 *   - a versioned envelope, so a future format change can be detected and
 *     ignored rather than crashing or silently restoring garbage
 *   - every storage access guarded: Safari private mode and quota exhaustion
 *     both throw, and losing persistence must never break the canvas
 *   - autosave debounced, so pen strokes do not each trigger a write
 */

import type { Editor } from "tldraw";

/** Bump when the stored shape changes; older envelopes are then ignored. */
export const SNAPSHOT_VERSION = 1;

export interface StoredSnapshot {
  version: number;
  updatedAt: string;
  snapshot: unknown;
}

const NOT_IMPLEMENTED = "canvas persistence is not implemented yet";

/** Namespaced localStorage key for one session's canvas. */
export function sessionStorageKey(_sessionId: string): string {
  throw new Error(NOT_IMPLEMENTED);
}

/** Serialize the current document. Returns false if storage was unavailable. */
export function saveCanvas(_editor: Editor, _sessionId: string): boolean {
  throw new Error(NOT_IMPLEMENTED);
}

/** Restore a stored document. Returns false when there is nothing usable. */
export function loadCanvas(_editor: Editor, _sessionId: string): boolean {
  throw new Error(NOT_IMPLEMENTED);
}

/** Forget one session's stored canvas. */
export function clearCanvas(_sessionId: string): void {
  throw new Error(NOT_IMPLEMENTED);
}

/** Persist on change, debounced. Returns a dispose function. */
export function startAutosave(
  _editor: Editor,
  _sessionId: string,
  _options?: { debounceMs?: number },
): () => void {
  throw new Error(NOT_IMPLEMENTED);
}
