import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Space } from "@/types/domain";

const createSpace = vi.fn();

vi.mock("@/lib/api/api", () => ({ createSpace }));

import {
  clearLegacySpaces,
  legacySpaceIds,
  migrateLegacySpaces,
} from "@/lib/spaces/migration";

const serverSpace = {
  id: "space_server",
  course_id: "course_demo",
  title: "Server space",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
} satisfies Space;

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});

describe("legacy space migration", () => {
  it("creates a server record with the old id and removes the migrated entry", async () => {
    localStorage.setItem(
      "mentora:spaces",
      JSON.stringify([
        {
          id: "space_old",
          courseId: "course_demo",
          title: "Old space",
        },
      ]),
    );
    createSpace.mockResolvedValue({ ...serverSpace, id: "space_old", title: "Old space" });

    const result = await migrateLegacySpaces("course_demo", []);

    expect(createSpace).toHaveBeenCalledWith("course_demo", {
      space_id: "space_old",
      title: "Old space",
      problem_id: undefined,
    });
    expect(result.spaces).toEqual([{ ...serverSpace, id: "space_old", title: "Old space" }]);
    expect(localStorage.getItem("mentora:spaces")).toBeNull();
  });

  it("does not remove a legacy space from another course", async () => {
    localStorage.setItem(
      "mentora:spaces",
      JSON.stringify([
        { id: "space_other", courseId: "course_other", title: "Other" },
      ]),
    );

    await migrateLegacySpaces("course_demo", []);

    expect(createSpace).not.toHaveBeenCalled();
    expect(legacySpaceIds("course_other")).toEqual(["space_other"]);
  });

  it("clears all legacy spaces for a deleted course", () => {
    localStorage.setItem(
      "mentora:spaces",
      JSON.stringify([
        { id: "space_one", courseId: "course_demo" },
        { id: "space_two", courseId: "course_other" },
      ]),
    );

    clearLegacySpaces("course_demo");

    expect(legacySpaceIds("course_demo")).toEqual([]);
    expect(legacySpaceIds("course_other")).toEqual(["space_two"]);
  });
});
