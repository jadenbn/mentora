import { beforeEach, describe, expect, it } from "vitest";
import { getStudentId } from "@/lib/student/identity";

beforeEach(() => {
  localStorage.clear();
});

describe("getStudentId", () => {
  it("defaults to dev-student — matching the dev dashboard's own default,\n" +
     "so completing a problem in the app and opening /dev/dashboard shows\n" +
     "the same student without any manual id reconciliation", () => {
    expect(getStudentId()).toBe("dev-student");
  });

  it("persists the id across calls", () => {
    const first = getStudentId();
    localStorage.setItem("mentora:student-id", "some-other-id");
    expect(getStudentId()).toBe("some-other-id");
    expect(first).toBe("dev-student");
  });

  it("respects a manually chosen id already in storage", () => {
    localStorage.setItem("mentora:student-id", "custom-student");
    expect(getStudentId()).toBe("custom-student");
  });
});
