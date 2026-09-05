import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  generate: vi.fn(),
  list: vi.fn(),
  push: vi.fn(),
  createSpace: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/lib/api/api", () => ({
  createSpace: mocks.createSpace,
  generateCourseQuestion: mocks.generate,
  listCourseDocuments: mocks.list,
  uploadCourseDocument: vi.fn(),
}));

import { CourseMaterials } from "@/features/materials/CourseMaterials";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
  .IS_REACT_ACT_ENVIRONMENT = true;

const documentRecord = {
  document_id: "doc_1",
  course_id: "course_1",
  filename: "lecture.pdf",
  document_type: "lecture" as const,
  total_chunks: 2,
  total_pages: 1,
  extracted_characters: 100,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("course-material question request", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    container = window.document.createElement("div");
    window.document.body.append(container);
    root = createRoot(container);
    mocks.list.mockResolvedValue([documentRecord]);
    mocks.generate.mockResolvedValue({
      id: "problem_1",
      course_id: "course_1",
      document_id: "doc_1",
      source: "generated",
      prompt: "Question",
    });
    mocks.createSpace.mockResolvedValue({ id: "space_1" });
    await act(async () => {
      root.render(createElement(CourseMaterials, { courseId: "course_1" }));
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.clearAllMocks();
  });

  it("requires and forwards the requested question type", async () => {
    const button = container.querySelector("button[type=button]") as HTMLButtonElement;
    const input = container.querySelector(
      'input[aria-label="Question request for lecture.pdf"]',
    ) as HTMLInputElement;
    expect(button.disabled).toBe(true);

    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      setValue?.call(input, "A difficult conceptual question");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(button.disabled).toBe(false);

    await act(async () => button.click());
    expect(mocks.generate).toHaveBeenCalledWith(
      "course_1",
      "doc_1",
      "A difficult conceptual question",
    );
    expect(mocks.createSpace).toHaveBeenCalledWith("course_1", {
      title: "Practice — lecture",
      problem_id: "problem_1",
    });
    expect(mocks.push).toHaveBeenCalledWith("/spaces/space_1");
  });
});
