import { createShapeId } from "tldraw";
import type { Editor, TLShapeId, TLShapePartial } from "tldraw";
import {
  AI_SHAPE_OWNER,
  SYSTEM_SHAPE_OWNER,
} from "@/lib/canvas/ownership";
import { studentContentBounds } from "@/lib/canvas/capture";

export const VERTICAL_PAGE_ID = createShapeId("mentora-vertical-page");

const PAGE_WIDTH = 900;
const INITIAL_PAGE_HEIGHT = 1_400;
const PAGE_MARGIN = 40;
const BOTTOM_PADDING_SCREEN_PX = 200;
const DEFAULT_BOTTOM_PADDING_WORLD = 240;
const GROWTH_CHUNK = 800;

export const VERTICAL_PAGE_PADDING = 24;

export function nextVerticalPageHeight(
  currentHeight: number,
  pageTop: number,
  contentBottom: number,
  bottomPadding = DEFAULT_BOTTOM_PADDING_WORLD,
): number {
  const trigger = pageTop + currentHeight - bottomPadding;
  if (contentBottom <= trigger) return currentHeight;
  const requiredHeight = contentBottom - pageTop + bottomPadding;
  return Math.max(
    currentHeight,
    Math.ceil(requiredHeight / GROWTH_CHUNK) * GROWTH_CHUNK,
  );
}

/** Create the transparent sheet boundary once and keep it behind all work. */
export function ensureVerticalPage(editor: Editor): boolean {
  const existing = editor.getShape(VERTICAL_PAGE_ID);
  if (existing) {
    const props = existing.props as {
      fill?: unknown;
      color?: unknown;
    };
    if (props.fill === "none" && existing.opacity === 0) return false;
    editor.run(
      () =>
        editor.updateShape({
          id: VERTICAL_PAGE_ID,
          type: "geo",
          opacity: 0,
          props: { fill: "none", color: "grey" },
        }),
      { history: "ignore", ignoreShapeLock: true },
    );
    return true;
  }

  const viewport = editor.getViewportPageBounds();
  const page: TLShapePartial = {
    id: VERTICAL_PAGE_ID,
    type: "geo",
    x: viewport.x + PAGE_MARGIN,
    y: viewport.y + PAGE_MARGIN,
    isLocked: true,
    opacity: 0,
    meta: { owner: SYSTEM_SHAPE_OWNER, role: "vertical-page" },
    props: {
      geo: "rectangle",
      w: PAGE_WIDTH,
      h: INITIAL_PAGE_HEIGHT,
      color: "grey",
      fill: "none",
      dash: "solid",
      size: "s",
    },
  };
  editor.createShapes([page]);
  editor.sendToBack([VERTICAL_PAGE_ID]);
  return true;
}

/** Put a new session at a readable width while keeping its top in view. */
export function positionVerticalPageCamera(editor: Editor): boolean {
  const page = editor.getShape(VERTICAL_PAGE_ID);
  const bounds = page ? editor.getShapePageBounds(page) : undefined;
  if (!bounds) return false;

  const viewport = editor.getViewportScreenBounds();
  const zoom = Math.min(
    1,
    Math.max(0.01, (viewport.w - VERTICAL_PAGE_PADDING * 2) / bounds.w),
  );
  editor.setCamera({
    x: -bounds.x + (viewport.w / zoom - bounds.w) / 2,
    y: -bounds.y + VERTICAL_PAGE_PADDING / zoom,
    z: zoom,
  });
  return true;
}

/** Grow only downward; existing work never moves or gets clipped. */
export function growVerticalPage(editor: Editor): boolean {
  const page = editor.getShape(VERTICAL_PAGE_ID);
  const content = studentContentBounds(editor);
  if (!page || !content) return false;

  const props = page.props as { w?: unknown; h?: unknown };
  const pageX = Number(page.x);
  const pageY = Number(page.y);
  const pageWidth = Number(props.w);
  const currentHeight = Number(props.h);
  if (
    !Number.isFinite(pageX) ||
    !Number.isFinite(pageY) ||
    !Number.isFinite(pageWidth) ||
    !Number.isFinite(currentHeight) ||
    pageWidth <= 0 ||
    currentHeight <= 0
  ) {
    return false;
  }

  const nextHeight = nextVerticalPageHeight(
    currentHeight,
    pageY,
    content.y + content.h,
    BOTTOM_PADDING_SCREEN_PX / Math.max(editor.getZoomLevel(), 0.01),
  );
  if (nextHeight === currentHeight) return false;

  editor.run(
    () =>
      editor.updateShape({
        id: VERTICAL_PAGE_ID,
        type: "geo",
        props: { h: nextHeight },
      }),
    { history: "ignore", ignoreShapeLock: true },
  );
  const updatedPage = editor.getShape(VERTICAL_PAGE_ID);
  const updatedHeight = Number(
    (updatedPage?.props as { h?: unknown } | undefined)?.h,
  );
  return updatedHeight === nextHeight;
}

/** Keep student content within the finite page, while allowing it to grow downward. */
export function removeStudentShapesOutsidePage(editor: Editor): boolean {
  const page = editor.getShape(VERTICAL_PAGE_ID);
  if (!page) return false;

  const props = page.props as { w?: unknown; h?: unknown };
  const pageX = Number(page.x);
  const pageY = Number(page.y);
  const pageWidth = Number(props.w);
  const pageHeight = Number(props.h);
  if (
    !Number.isFinite(pageX) ||
    !Number.isFinite(pageY) ||
    !Number.isFinite(pageWidth) ||
    !Number.isFinite(pageHeight) ||
    pageWidth <= 0 ||
    pageHeight <= 0
  ) {
    return false;
  }

  const outside: TLShapeId[] = [];
  for (const id of editor.getCurrentPageShapeIds()) {
    const shape = editor.getShape(id);
    const owner = shape?.meta?.owner;
    if (!shape || owner === SYSTEM_SHAPE_OWNER || owner === AI_SHAPE_OWNER) {
      continue;
    }
    const bounds = editor.getShapePageBounds(shape);
    if (
      bounds &&
      (bounds.x < pageX ||
        bounds.x + bounds.w > pageX + pageWidth ||
        bounds.y < pageY ||
        bounds.y + bounds.h > pageY + pageHeight)
    ) {
      outside.push(id);
    }
  }

  if (outside.length === 0) return false;
  editor.run(
    () => editor.deleteShapes(outside),
    { history: "ignore" },
  );
  return true;
}
