import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  listSpaces: vi.fn(),
  createSpace: vi.fn(),
  deleteSpaceById: vi.fn(),
  clearCanvas: vi.fn(),
  getSpaceById: vi.fn(),
  getCourseById: vi.fn(),
  updateSpace: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/lib/api/api", () => ({
  listSpaces: mocks.listSpaces,
  createSpace: mocks.createSpace,
  deleteSpaceById: mocks.deleteSpaceById,
  getSpaceById: mocks.getSpaceById,
  getCourseById: mocks.getCourseById,
  updateSpace: mocks.updateSpace,
}));
vi.mock("@/lib/canvas/persistence", () => ({ clearCanvas: mocks.clearCanvas }));
vi.mock("@/features/whiteboard/Whiteboard", () => ({
  Whiteboard: () => null,
}));

import { SpaceGrid } from "@/features/spaces/SpaceGrid";
import { SpaceWorkspace } from "@/features/spaces/SpaceWorkspace";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
  .IS_REACT_ACT_ENVIRONMENT = true;

const spaceRecord = {
  id: "space_1",
  course_id: "course_1",
  title: "Warmup",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

async function mount(element: ReturnType<typeof createElement>) {
  const container = window.document.createElement("div");
  window.document.body.append(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(element);
  });
  return { container, root };
}

async function unmount(container: HTMLDivElement, root: Root) {
  await act(async () => root.unmount());
  container.remove();
}

describe("SpaceGrid", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows an empty state when the course has no spaces", async () => {
    mocks.listSpaces.mockResolvedValue([]);
    const { container, root } = await mount(createElement(SpaceGrid, { courseId: "course_1" }));
    expect(container.textContent).toMatch(/no spaces yet/i);
    await unmount(container, root);
  });

  it("lists spaces returned by the API", async () => {
    mocks.listSpaces.mockResolvedValue([spaceRecord]);
    const { container, root } = await mount(createElement(SpaceGrid, { courseId: "course_1" }));
    expect(container.textContent).toContain("Warmup");
    await unmount(container, root);
  });

  it("creates a space and navigates to it", async () => {
    mocks.listSpaces.mockResolvedValue([]);
    mocks.createSpace.mockResolvedValue({ ...spaceRecord, id: "space_new" });
    const { container, root } = await mount(createElement(SpaceGrid, { courseId: "course_1" }));

    const createButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "New space",
    ) as HTMLButtonElement;
    await act(async () => createButton.click());

    expect(mocks.createSpace).toHaveBeenCalledWith("course_1");
    expect(mocks.push).toHaveBeenCalledWith("/spaces/space_new");
    await unmount(container, root);
  });

  it("deletes a space and clears its canvas after confirmation", async () => {
    mocks.listSpaces.mockResolvedValue([spaceRecord]);
    mocks.deleteSpaceById.mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { container, root } = await mount(createElement(SpaceGrid, { courseId: "course_1" }));

    const deleteButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Delete",
    ) as HTMLButtonElement;
    await act(async () => deleteButton.click());

    expect(mocks.deleteSpaceById).toHaveBeenCalledWith("course_1", "space_1");
    expect(mocks.clearCanvas).toHaveBeenCalledWith("space_1");
    expect(container.textContent).toMatch(/no spaces yet/i);
    await unmount(container, root);
  });

  it("does not delete when the confirmation is declined", async () => {
    mocks.listSpaces.mockResolvedValue([spaceRecord]);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const { container, root } = await mount(createElement(SpaceGrid, { courseId: "course_1" }));

    const deleteButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Delete",
    ) as HTMLButtonElement;
    await act(async () => deleteButton.click());

    expect(mocks.deleteSpaceById).not.toHaveBeenCalled();
    await unmount(container, root);
  });
});

describe("SpaceWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a not-found state when the space does not exist", async () => {
    mocks.getSpaceById.mockResolvedValue(null);
    const { container, root } = await mount(createElement(SpaceWorkspace, { spaceId: "nope" }));
    expect(container.textContent).toMatch(/space not found/i);
    await unmount(container, root);
  });

  it("shows the course name once both the space and course have loaded", async () => {
    mocks.getSpaceById.mockResolvedValue(spaceRecord);
    mocks.getCourseById.mockResolvedValue({
      id: "course_1",
      name: "MATH 101",
      description: "",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    const { container, root } = await mount(
      createElement(SpaceWorkspace, { spaceId: "space_1" }),
    );
    expect(container.textContent).toContain("MATH 101");
    expect(container.textContent).toContain("Warmup");
    await unmount(container, root);
  });

  it("renames the space via the API when given a non-blank title", async () => {
    mocks.getSpaceById.mockResolvedValue(spaceRecord);
    mocks.getCourseById.mockResolvedValue(null);
    mocks.updateSpace.mockResolvedValue({ ...spaceRecord, title: "Renamed" });
    vi.spyOn(window, "prompt").mockReturnValue("Renamed");
    const { container, root } = await mount(
      createElement(SpaceWorkspace, { spaceId: "space_1" }),
    );

    const renameButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Rename",
    ) as HTMLButtonElement;
    await act(async () => renameButton.click());

    expect(mocks.updateSpace).toHaveBeenCalledWith("course_1", "space_1", { title: "Renamed" });
    await unmount(container, root);
  });

  it("ignores a blank rename rather than clearing the title", async () => {
    mocks.getSpaceById.mockResolvedValue(spaceRecord);
    mocks.getCourseById.mockResolvedValue(null);
    vi.spyOn(window, "prompt").mockReturnValue("   ");
    const { container, root } = await mount(
      createElement(SpaceWorkspace, { spaceId: "space_1" }),
    );

    const renameButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Rename",
    ) as HTMLButtonElement;
    await act(async () => renameButton.click());

    expect(mocks.updateSpace).not.toHaveBeenCalled();
    await unmount(container, root);
  });
});
