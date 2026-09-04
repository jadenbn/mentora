import { describe, expect, it } from "vitest";
import {
  growVerticalPage,
  nextVerticalPageHeight,
  removeStudentShapesOutsidePage,
  VERTICAL_PAGE_ID,
} from "@/lib/canvas/verticalPage";
import { SYSTEM_SHAPE_OWNER } from "@/lib/canvas/ownership";
import { box, makeEditor } from "./fakeEditor";

describe("nextVerticalPageHeight", () => {
  it("keeps the current page when work is comfortably inside it", () => {
    expect(nextVerticalPageHeight(1_400, 0, 1_000)).toBe(1_400);
  });

  it("grows in chunks when work enters the bottom safety zone", () => {
    expect(nextVerticalPageHeight(1_400, 0, 1_300)).toBe(1_600);
  });

  it("preserves the page top when the document is offset in world space", () => {
    expect(nextVerticalPageHeight(1_400, 500, 1_900)).toBe(2_400);
  });

  it("accepts a zoom-adjusted safety margin", () => {
    expect(nextVerticalPageHeight(1_400, 0, 1_150, 400)).toBe(1_600);
  });

  it("grows the stored page when student work enters the bottom zone", () => {
    const { editor, shapes } = makeEditor({
      shapes: [
        {
          id: VERTICAL_PAGE_ID,
          type: "geo",
          x: 100,
          y: 200,
          isLocked: true,
          meta: { owner: SYSTEM_SHAPE_OWNER },
          props: { w: 900, h: 1_400 },
        },
        {
          id: "student-stroke",
          type: "draw",
          pageBounds: box(300, 1_400, 40, 80),
        },
      ],
      zoom: 1,
    });

    expect(growVerticalPage(editor)).toBe(true);
    expect(shapes.get(VERTICAL_PAGE_ID)?.props?.h).toBe(1_600);
  });

  it("removes student work that crosses a fixed page edge", () => {
    const { editor, deleted } = makeEditor({
      shapes: [
        {
          id: VERTICAL_PAGE_ID,
          type: "geo",
          x: 100,
          y: 200,
          isLocked: true,
          meta: { owner: SYSTEM_SHAPE_OWNER },
          props: { w: 900, h: 1_400 },
        },
        {
          id: "outside-stroke",
          type: "draw",
          pageBounds: box(950, 400, 80, 20),
        },
      ],
    });

    expect(removeStudentShapesOutsidePage(editor)).toBe(true);
    expect(deleted).toEqual(["outside-stroke"]);
  });
});
