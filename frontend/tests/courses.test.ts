import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  confirm: vi.fn(),
  deleteCourseById: vi.fn(),
  listSpaces: vi.fn(),
  push: vi.fn(),
  clearCanvas: vi.fn(),
  clearFeedbackHistory: vi.fn(),
  clearLegacySpaces: vi.fn(),
  legacySpaceIds: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/lib/api/api", () => ({
  deleteCourseById: mocks.deleteCourseById,
  listSpaces: mocks.listSpaces,
}));
vi.mock("@/lib/canvas/persistence", () => ({ clearCanvas: mocks.clearCanvas }));
vi.mock("@/lib/tutor/feedbackHistory", () => ({
  clearFeedbackHistory: mocks.clearFeedbackHistory,
}));
vi.mock("@/lib/spaces/migration", () => ({
  clearLegacySpaces: mocks.clearLegacySpaces,
  legacySpaceIds: mocks.legacySpaceIds,
}));

import { DeleteCourseButton } from "@/features/courses/DeleteCourseButton";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
  .IS_REACT_ACT_ENVIRONMENT = true;

describe("DeleteCourseButton", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    mocks.confirm.mockReturnValue(true);
    mocks.listSpaces.mockResolvedValue([{ id: "space_1" }]);
    mocks.legacySpaceIds.mockReturnValue(["space_old"]);
    mocks.deleteCourseById.mockResolvedValue(undefined);
    container = window.document.createElement("div");
    window.document.body.append(container);
    root = createRoot(container);
  });

  it("clears server and legacy local space data after deletion", async () => {
    await act(async () => {
      root.render(createElement(DeleteCourseButton, {
        courseId: "course_1",
        courseName: "MATH 101",
      }));
    });
    vi.spyOn(window, "confirm").mockImplementation(mocks.confirm);

    await act(async () => {
      (container.querySelector("button") as HTMLButtonElement).click();
    });

    expect(mocks.listSpaces).toHaveBeenCalledWith("course_1");
    expect(mocks.deleteCourseById).toHaveBeenCalledWith("course_1");
    expect(mocks.clearCanvas).toHaveBeenCalledWith("space_1");
    expect(mocks.clearCanvas).toHaveBeenCalledWith("space_old");
    expect(mocks.clearFeedbackHistory).toHaveBeenCalledWith("space_1");
    expect(mocks.clearFeedbackHistory).toHaveBeenCalledWith("space_old");
    expect(mocks.clearLegacySpaces).toHaveBeenCalledWith("course_1");
    expect(mocks.push).toHaveBeenCalledWith("/courses");

    await act(async () => root.unmount());
    container.remove();
  });
});
