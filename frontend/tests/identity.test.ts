import { beforeEach, describe, expect, it } from "vitest";
import { getStudentId } from "@/lib/student/identity";

beforeEach(() => {
  localStorage.clear();
});

describe("getStudentId", () => {
  it("mints a distinct id per browser rather than a shared default", () => {
    const id = getStudentId();
    expect(id).toMatch(/^student_[a-z0-9]+$/);
    expect(id).not.toBe("dev-student");
    expect(localStorage.getItem("mentora:student-id")).toBe(id);
  });

  it("persists the id across calls", () => {
    const first = getStudentId();
    expect(getStudentId()).toBe(first);
  });

  it("respects a manually chosen id already in storage", () => {
    localStorage.setItem("mentora:student-id", "custom-student");
    expect(getStudentId()).toBe("custom-student");
  });
});
