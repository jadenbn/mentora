/**
 * SPECIFICATION for canvas persistence — the next feature to build.
 *
 * Every test here currently FAILS against the stub in lib/canvas/persistence.ts.
 * That is intentional: each failure names one behaviour to implement. When they
 * all pass, the feature is done.
 *
 * The product gap being closed: reloading a session today loses all student
 * work, because nothing persists the tldraw document.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Editor } from "tldraw";
import {
  SNAPSHOT_VERSION,
  clearCanvas,
  loadCanvas,
  saveCanvas,
  sessionStorageKey,
  startAutosave,
} from "@/lib/canvas/persistence";

const getSnapshotMock = vi.fn(() => ({ document: { shapes: ["a"] } }));
const loadSnapshotMock = vi.fn();

vi.mock("tldraw", async (importOriginal) => ({
  ...(await importOriginal<typeof import("tldraw")>()),
  getSnapshot: (...args: unknown[]) => getSnapshotMock(...(args as [])),
  loadSnapshot: (...args: unknown[]) => loadSnapshotMock(...(args as [])),
}));

/** An editor exposing just the store surface persistence needs. */
function makeStoreEditor() {
  const listeners: (() => void)[] = [];
  const editor = {
    store: {
      listen: vi.fn((fn: () => void) => {
        listeners.push(fn);
        return () => {
          const i = listeners.indexOf(fn);
          if (i >= 0) listeners.splice(i, 1);
        };
      }),
    },
  } as unknown as Editor;
  return { editor, emitChange: () => listeners.forEach((fn) => fn()), listeners };
}

beforeEach(() => {
  localStorage.clear();
  getSnapshotMock.mockClear();
  loadSnapshotMock.mockClear();
});

describe("sessionStorageKey", () => {
  it("namespaces the key so it cannot collide with other apps", () => {
    expect(sessionStorageKey("session_1")).toMatch(/mentora/i);
  });

  it("includes the session id", () => {
    expect(sessionStorageKey("session_abc")).toContain("session_abc");
  });

  it("gives different sessions different keys", () => {
    expect(sessionStorageKey("a")).not.toBe(sessionStorageKey("b"));
  });

  it("is stable across calls", () => {
    expect(sessionStorageKey("a")).toBe(sessionStorageKey("a"));
  });
});

describe("saveCanvas", () => {
  it("writes something under the session's key", () => {
    const { editor } = makeStoreEditor();
    saveCanvas(editor, "session_1");
    expect(localStorage.getItem(sessionStorageKey("session_1"))).toBeTruthy();
  });

  it("reports success", () => {
    const { editor } = makeStoreEditor();
    expect(saveCanvas(editor, "session_1")).toBe(true);
  });

  it("stores a versioned envelope so a format change can be detected later", () => {
    const { editor } = makeStoreEditor();
    saveCanvas(editor, "session_1");
    const stored = JSON.parse(
      localStorage.getItem(sessionStorageKey("session_1"))!,
    );
    expect(stored.version).toBe(SNAPSHOT_VERSION);
    expect(stored).toHaveProperty("snapshot");
  });

  it("records when the snapshot was taken", () => {
    const { editor } = makeStoreEditor();
    saveCanvas(editor, "session_1");
    const stored = JSON.parse(
      localStorage.getItem(sessionStorageKey("session_1"))!,
    );
    expect(Number.isNaN(Date.parse(stored.updatedAt))).toBe(false);
  });

  it("serializes the editor's own store", () => {
    const { editor } = makeStoreEditor();
    saveCanvas(editor, "session_1");
    expect(getSnapshotMock).toHaveBeenCalledWith(editor.store);
  });

  it("replaces an earlier save rather than accumulating entries", () => {
    const { editor } = makeStoreEditor();
    saveCanvas(editor, "session_1");
    saveCanvas(editor, "session_1");
    expect(localStorage.length).toBe(1);
  });

  it("keeps sessions independent", () => {
    const { editor } = makeStoreEditor();
    saveCanvas(editor, "session_a");
    saveCanvas(editor, "session_b");
    expect(localStorage.getItem(sessionStorageKey("session_a"))).toBeTruthy();
    expect(localStorage.getItem(sessionStorageKey("session_b"))).toBeTruthy();
  });

  it("returns false instead of throwing when storage is unavailable", () => {
    // Safari private mode and quota exhaustion both throw on setItem.
    const { editor } = makeStoreEditor();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError");
    });
    expect(saveCanvas(editor, "session_1")).toBe(false);
  });
});

describe("loadCanvas", () => {
  it("reports failure when nothing has been saved", () => {
    const { editor } = makeStoreEditor();
    expect(loadCanvas(editor, "session_1")).toBe(false);
  });

  it("does not touch the editor when there is nothing to restore", () => {
    const { editor } = makeStoreEditor();
    loadCanvas(editor, "session_1");
    expect(loadSnapshotMock).not.toHaveBeenCalled();
  });

  it("restores a previously saved document", () => {
    const { editor } = makeStoreEditor();
    saveCanvas(editor, "session_1");
    expect(loadCanvas(editor, "session_1")).toBe(true);
    expect(loadSnapshotMock).toHaveBeenCalled();
  });

  it("restores the snapshot that was stored, not the envelope", () => {
    const { editor } = makeStoreEditor();
    saveCanvas(editor, "session_1");
    loadCanvas(editor, "session_1");
    expect(loadSnapshotMock).toHaveBeenCalledWith(editor.store, {
      document: { shapes: ["a"] },
    });
  });

  it("ignores corrupt JSON instead of throwing", () => {
    const { editor } = makeStoreEditor();
    localStorage.setItem(sessionStorageKey("session_1"), "{not json");
    expect(loadCanvas(editor, "session_1")).toBe(false);
  });

  it("ignores a snapshot written by a newer format", () => {
    const { editor } = makeStoreEditor();
    localStorage.setItem(
      sessionStorageKey("session_1"),
      JSON.stringify({ version: SNAPSHOT_VERSION + 1, snapshot: {} }),
    );
    expect(loadCanvas(editor, "session_1")).toBe(false);
    expect(loadSnapshotMock).not.toHaveBeenCalled();
  });

  it("does not restore one session's canvas into another", () => {
    const { editor } = makeStoreEditor();
    saveCanvas(editor, "session_a");
    expect(loadCanvas(editor, "session_b")).toBe(false);
  });

  it("survives a failure inside the restore itself", () => {
    const { editor } = makeStoreEditor();
    saveCanvas(editor, "session_1");
    loadSnapshotMock.mockImplementationOnce(() => {
      throw new Error("bad snapshot");
    });
    expect(loadCanvas(editor, "session_1")).toBe(false);
  });
});

describe("clearCanvas", () => {
  it("forgets the stored canvas", () => {
    const { editor } = makeStoreEditor();
    saveCanvas(editor, "session_1");
    clearCanvas("session_1");
    expect(localStorage.getItem(sessionStorageKey("session_1"))).toBeNull();
  });

  it("leaves other sessions untouched", () => {
    const { editor } = makeStoreEditor();
    saveCanvas(editor, "session_a");
    saveCanvas(editor, "session_b");
    clearCanvas("session_a");
    expect(localStorage.getItem(sessionStorageKey("session_b"))).toBeTruthy();
  });

  it("is safe to call when nothing was saved", () => {
    expect(() => clearCanvas("session_1")).not.toThrow();
  });
});

describe("startAutosave", () => {
  beforeEach(() => vi.useFakeTimers());

  it("subscribes to store changes", () => {
    const { editor } = makeStoreEditor();
    startAutosave(editor, "session_1");
    expect(editor.store.listen).toHaveBeenCalled();
  });

  it("does not write before anything changes", () => {
    const { editor } = makeStoreEditor();
    startAutosave(editor, "session_1");
    vi.advanceTimersByTime(10_000);
    expect(localStorage.getItem(sessionStorageKey("session_1"))).toBeNull();
  });

  it("writes after a change settles", () => {
    const { editor, emitChange } = makeStoreEditor();
    startAutosave(editor, "session_1", { debounceMs: 500 });
    emitChange();
    vi.advanceTimersByTime(500);
    expect(localStorage.getItem(sessionStorageKey("session_1"))).toBeTruthy();
  });

  it("does not write while changes are still arriving", () => {
    const { editor, emitChange } = makeStoreEditor();
    startAutosave(editor, "session_1", { debounceMs: 500 });
    emitChange();
    vi.advanceTimersByTime(400);
    expect(localStorage.getItem(sessionStorageKey("session_1"))).toBeNull();
  });

  it("coalesces a burst of strokes into a single write", () => {
    const { editor, emitChange } = makeStoreEditor();
    startAutosave(editor, "session_1", { debounceMs: 500 });
    for (let i = 0; i < 50; i++) {
      emitChange();
      vi.advanceTimersByTime(10);
    }
    vi.advanceTimersByTime(500);
    expect(getSnapshotMock).toHaveBeenCalledTimes(1);
  });

  it("notifies onSave only after a write actually succeeds", () => {
    const { editor, emitChange } = makeStoreEditor();
    const onSave = vi.fn();
    startAutosave(editor, "session_1", { debounceMs: 100, onSave });

    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementationOnce(() => {
        throw new DOMException("QuotaExceededError");
      });
    emitChange();
    vi.advanceTimersByTime(100);
    expect(onSave).not.toHaveBeenCalled();

    setItem.mockRestore();
    emitChange();
    vi.advanceTimersByTime(100);
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("stops writing once disposed", () => {
    const { editor, emitChange } = makeStoreEditor();
    const dispose = startAutosave(editor, "session_1", { debounceMs: 500 });
    dispose();
    emitChange();
    vi.advanceTimersByTime(2_000);
    expect(localStorage.getItem(sessionStorageKey("session_1"))).toBeNull();
  });

  it("cancels a write that was already queued when disposed", () => {
    // Navigating away mid-stroke must not fire a save after teardown.
    const { editor, emitChange } = makeStoreEditor();
    const dispose = startAutosave(editor, "session_1", { debounceMs: 500 });
    emitChange();
    vi.advanceTimersByTime(400);
    dispose();
    vi.advanceTimersByTime(2_000);
    expect(localStorage.getItem(sessionStorageKey("session_1"))).toBeNull();
  });

  it("unsubscribes from the store on dispose", () => {
    const { editor, listeners } = makeStoreEditor();
    const dispose = startAutosave(editor, "session_1");
    dispose();
    expect(listeners).toHaveLength(0);
  });

  it("keeps autosaving after a failed write", () => {
    const { editor, emitChange } = makeStoreEditor();
    startAutosave(editor, "session_1", { debounceMs: 100 });
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementationOnce(() => {
        throw new DOMException("QuotaExceededError");
      });
    emitChange();
    vi.advanceTimersByTime(100);
    setItem.mockRestore();
    emitChange();
    vi.advanceTimersByTime(100);
    expect(localStorage.getItem(sessionStorageKey("session_1"))).toBeTruthy();
  });
});
