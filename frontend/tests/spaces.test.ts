import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionStorageKey } from "@/lib/canvas/persistence";
import {
  createSpace,
  deleteSpace,
  getServerSpacesSnapshot,
  getSpace,
  getSpacesSnapshot,
  listSpaces,
  renameSpace,
  subscribeToSpaces,
  touchSpace,
} from "@/lib/spaces/store";

beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
});

afterEach(() => vi.useRealTimers());

/** Advance the clock so successive writes get distinguishable timestamps. */
function tick(ms = 1000) {
  vi.setSystemTime(new Date(Date.now() + ms));
}

describe("createSpace", () => {
  it("returns a space belonging to the room", () => {
    const space = createSpace("room_demo");
    expect(space.roomId).toBe("room_demo");
  });

  it("gives each space a distinct id", () => {
    expect(createSpace("c").id).not.toBe(createSpace("c").id);
  });

  it("stamps both timestamps on creation", () => {
    const space = createSpace("c");
    expect(Number.isNaN(Date.parse(space.createdAt))).toBe(false);
    expect(space.updatedAt).toBe(space.createdAt);
  });

  it("numbers untitled spaces per room", () => {
    expect(createSpace("room_a").title).toBe("Space 1");
    expect(createSpace("room_a").title).toBe("Space 2");
    expect(createSpace("room_b").title).toBe("Space 1");
  });

  it("accepts a custom title", () => {
    expect(createSpace("c", "Integration practice").title).toBe(
      "Integration practice",
    );
  });

  it("trims a custom title", () => {
    expect(createSpace("c", "  Padded  ").title).toBe("Padded");
  });

  it("falls back to a default when the title is only whitespace", () => {
    expect(createSpace("c", "   ").title).toBe("Space 1");
  });

  it("persists across a reload", () => {
    const space = createSpace("c", "Kept");
    expect(getSpace(space.id)?.title).toBe("Kept");
  });
});

describe("listSpaces", () => {
  it("is empty for a room with no spaces", () => {
    expect(listSpaces("room_demo")).toEqual([]);
  });

  it("returns only that room's spaces", () => {
    createSpace("room_a", "A1");
    createSpace("room_b", "B1");
    expect(listSpaces("room_a").map((s) => s.title)).toEqual(["A1"]);
  });

  it("puts the most recently worked on space first", () => {
    const first = createSpace("c", "First");
    tick();
    createSpace("c", "Second");
    tick();
    touchSpace(first.id);
    expect(listSpaces("c").map((s) => s.title)).toEqual(["First", "Second"]);
  });
});

describe("renameSpace", () => {
  it("changes the title", () => {
    const space = createSpace("c", "Old");
    renameSpace(space.id, "New");
    expect(getSpace(space.id)?.title).toBe("New");
  });

  it("trims the new title", () => {
    const space = createSpace("c");
    renameSpace(space.id, "  Tidy  ");
    expect(getSpace(space.id)?.title).toBe("Tidy");
  });

  it("ignores a blank title rather than erasing the name", () => {
    const space = createSpace("c", "Keep");
    renameSpace(space.id, "   ");
    expect(getSpace(space.id)?.title).toBe("Keep");
  });

  it("leaves other spaces alone", () => {
    const a = createSpace("c", "A");
    const b = createSpace("c", "B");
    renameSpace(a.id, "Renamed");
    expect(getSpace(b.id)?.title).toBe("B");
  });
});

describe("touchSpace", () => {
  it("moves updatedAt forward", () => {
    const space = createSpace("c");
    tick();
    touchSpace(space.id);
    expect(getSpace(space.id)!.updatedAt > space.updatedAt).toBe(true);
  });

  it("leaves createdAt alone", () => {
    const space = createSpace("c");
    tick();
    touchSpace(space.id);
    expect(getSpace(space.id)!.createdAt).toBe(space.createdAt);
  });

  it("is a no-op for an unknown id", () => {
    const space = createSpace("c");
    touchSpace("nope");
    expect(getSpace(space.id)!.updatedAt).toBe(space.updatedAt);
  });
});

describe("deleteSpace", () => {
  it("removes the space from the index", () => {
    const space = createSpace("c");
    deleteSpace(space.id);
    expect(getSpace(space.id)).toBeNull();
  });

  it("also discards the canvas, so the id cannot be reused with stale work", () => {
    const space = createSpace("c");
    localStorage.setItem(sessionStorageKey(space.id), "{}");
    deleteSpace(space.id);
    expect(localStorage.getItem(sessionStorageKey(space.id))).toBeNull();
  });

  it("leaves other spaces intact", () => {
    const a = createSpace("c", "A");
    const b = createSpace("c", "B");
    deleteSpace(a.id);
    expect(listSpaces("c").map((s) => s.title)).toEqual(["B"]);
  });

  it("is safe for an unknown id", () => {
    expect(() => deleteSpace("nope")).not.toThrow();
  });
});

describe("external store contract", () => {
  it("returns the same reference until something changes", () => {
    // useSyncExternalStore re-renders forever if this is not stable.
    createSpace("c");
    expect(getSpacesSnapshot()).toBe(getSpacesSnapshot());
  });

  it("returns a new reference after a write", () => {
    createSpace("c");
    const before = getSpacesSnapshot();
    createSpace("c");
    expect(getSpacesSnapshot()).not.toBe(before);
  });

  it("serves an empty list on the server", () => {
    expect(getServerSpacesSnapshot()).toEqual([]);
  });

  it("notifies subscribers when a space is created", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToSpaces(listener);
    createSpace("c");
    expect(listener).toHaveBeenCalled();
    unsubscribe();
  });

  it("stops notifying after unsubscribe", () => {
    const listener = vi.fn();
    subscribeToSpaces(listener)();
    createSpace("c");
    expect(listener).not.toHaveBeenCalled();
  });
});

describe("hostile storage", () => {
  it("treats a corrupt index as empty rather than throwing", () => {
    localStorage.setItem("mentora:spaces", "{not json");
    expect(listSpaces("c")).toEqual([]);
  });

  it("ignores an index that is not an array", () => {
    localStorage.setItem("mentora:spaces", JSON.stringify({ nope: true }));
    expect(listSpaces("c")).toEqual([]);
  });

  it("does not throw when the index cannot be written", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError");
    });
    expect(() => createSpace("c")).not.toThrow();
  });
});
