/**
 * The registry of whiteboard spaces, kept in localStorage.
 *
 * This holds only the index — id, course, title, timestamps. The canvas
 * document itself lives under its own key, managed by lib/canvas/persistence.
 * Splitting them means listing spaces never has to parse a full tldraw
 * snapshot.
 *
 * Storage access is guarded throughout, for the same reasons as persistence:
 * blocked site data and quota exhaustion both throw, and neither should take
 * the page down.
 */

import { clearCanvas } from "@/lib/canvas/persistence";
import type { ProblemContext, Space } from "@/types/domain";

const INDEX_KEY = "mentora:spaces";

/** Stable empty result, so snapshots stay referentially equal. */
const EMPTY: Space[] = [];

const listeners = new Set<() => void>();

/**
 * useSyncExternalStore requires getSnapshot to return the same reference until
 * the data actually changes, so the parsed list is cached against its raw JSON.
 */
let cache: { raw: string | null; spaces: Space[] } | null = null;

function invalidate(): void {
  cache = null;
  for (const listener of listeners) {
    listener();
  }
}

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

function parse(raw: string | null): Space[] {
  if (!raw) {
    return EMPTY;
  }
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as Space[]) : EMPTY;
  } catch {
    return EMPTY;
  }
}

function readAll(): Space[] {
  const store = storage();
  if (!store) {
    return EMPTY;
  }
  let raw: string | null;
  try {
    raw = store.getItem(INDEX_KEY);
  } catch {
    return EMPTY;
  }
  if (!cache || cache.raw !== raw) {
    cache = { raw, spaces: parse(raw) };
  }
  return cache.spaces;
}

/** Subscribe to space-index changes, including writes from another tab. */
export function subscribeToSpaces(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === INDEX_KEY) {
      invalidate();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** Snapshot for useSyncExternalStore. Referentially stable between writes. */
export function getSpacesSnapshot(): Space[] {
  return readAll();
}

/** There is no localStorage on the server, so the list starts empty. */
export function getServerSpacesSnapshot(): Space[] {
  return EMPTY;
}

function writeAll(spaces: Space[]): boolean {
  const store = storage();
  if (!store) {
    return false;
  }
  try {
    store.setItem(INDEX_KEY, JSON.stringify(spaces));
    invalidate();
    return true;
  } catch {
    return false;
  }
}

function newId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `space_${Date.now().toString(36)}`;
  }
}

/** Spaces for one course, most recently worked on first. */
export function listSpaces(courseId: string): Space[] {
  return readAll()
    .filter((space) => space.courseId === courseId)
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export function getSpace(spaceId: string): Space | null {
  return readAll().find((space) => space.id === spaceId) ?? null;
}

export function createSpace(
  courseId: string,
  title?: string,
  problem?: ProblemContext,
): Space {
  const existing = readAll();
  const now = new Date().toISOString();
  const untitled = existing.filter((s) => s.courseId === courseId).length + 1;

  const space: Space = {
    id: newId(),
    courseId,
    title: title?.trim() || `Space ${untitled}`,
    createdAt: now,
    updatedAt: now,
    ...(problem ? { problem } : {}),
  };

  if (!writeAll([space, ...existing])) {
    throw new Error("Could not save this Space on the device.");
  }
  return space;
}

export function renameSpace(spaceId: string, title: string): void {
  const trimmed = title.trim();
  if (!trimmed) {
    return;
  }
  writeAll(
    readAll().map((space) =>
      space.id === spaceId
        ? { ...space, title: trimmed, updatedAt: new Date().toISOString() }
        : space,
    ),
  );
}

/** Record that a space was just worked on, so it sorts to the front. */
export function touchSpace(spaceId: string): void {
  const now = new Date().toISOString();
  const all = readAll();
  if (!all.some((space) => space.id === spaceId)) {
    return;
  }
  writeAll(
    all.map((space) =>
      space.id === spaceId ? { ...space, updatedAt: now } : space,
    ),
  );
}

/** Remove a space and the canvas document that belongs to it. */
export function deleteSpace(spaceId: string): void {
  writeAll(readAll().filter((space) => space.id !== spaceId));
  clearCanvas(spaceId);
}
