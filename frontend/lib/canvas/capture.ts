/**
 * Canvas capture boundary (ARCHITECTURE.md section 20).
 *
 * Hides tldraw export details from the rest of the app and, critically, reports
 * the world-space rectangle the exported image covers. The tutor answers in
 * coordinates normalized to that image, so the renderer needs this rectangle to
 * map them back onto the canvas.
 */

import type { Box, Editor, TLShapeId } from "tldraw";
import type {
  CanvasContext,
  CanvasShape,
  NormalizedBounds,
  ShapeOwner,
} from "../../types/tutor.ts";
import { readPngDimensions } from "./png.ts";

/** Keeps the upload well under the backend's 10 MB limit. */
const MAX_IMAGE_EDGE = 1280;
const CAPTURE_MARGIN = 12;

export interface CanvasCapture {
  blob: Blob;
  width: number;
  height: number;
  /** World-space rectangle the image covers. */
  bounds: Box;
  /** Shapes actually included in the clean analysis image. */
  shapeIds: TLShapeId[];
}

export async function captureCanvasForAnalysis(
  editor: Editor,
): Promise<CanvasCapture | null> {
  const ownedShapeIds = [...editor.getCurrentPageShapeIds()].map((id) => {
    const shape = editor.getShape(id);
    return { id, owner: shape ? readOwner(shape.meta) : null };
  });
  const studentShapeIds = ownedShapeIds
    .filter(({ owner }) => owner === "student")
    .map(({ id }) => id);
  const systemShapeIds = ownedShapeIds
    .filter(({ owner }) => owner === "system")
    .map(({ id }) => id);

  // The problem is already supplied as structured context. A tight crop of
  // student work preserves small notation such as superscripts. On a blank
  // board, system/problem shapes are the useful fallback for Stuck/Explain.
  // AI feedback remains visible on the board but never re-enters analysis.
  const shapeIds =
    studentShapeIds.length > 0 ? studentShapeIds : systemShapeIds;
  if (shapeIds.length === 0) {
    return null;
  }

  const shapeBounds = editor.getShapesPageBounds(shapeIds);
  if (!shapeBounds || shapeBounds.w <= 0 || shapeBounds.h <= 0) {
    return null;
  }
  // Preserve tldraw's Box prototype: toImage clones the supplied bounds.
  const bounds =
    typeof shapeBounds.clone === "function"
      ? shapeBounds.clone().expandBy(CAPTURE_MARGIN)
      : ({
          x: shapeBounds.x - CAPTURE_MARGIN,
          y: shapeBounds.y - CAPTURE_MARGIN,
          w: shapeBounds.w + CAPTURE_MARGIN * 2,
          h: shapeBounds.h + CAPTURE_MARGIN * 2,
        } as Box);

  const scale = Math.min(1, MAX_IMAGE_EDGE / Math.max(bounds.w, bounds.h));

  const image = await editor.toImage(shapeIds, {
    format: "png",
    background: true,
    padding: 0,
    bounds,
    scale,
  });

  if (!image?.blob) {
    return null;
  }

  // tldraw's returned width/height describe its logical export bounds and may
  // be fractional. The versioned tutor schema requires the encoded image's
  // integer pixel dimensions, which PNG stores in the IHDR header.
  const dimensions = await readPngDimensions(image.blob);

  return {
    blob: image.blob,
    width: dimensions.width,
    height: dimensions.height,
    bounds,
    shapeIds,
  };
}

/**
 * Normalize a world-space box against the captured frame.
 *
 * The backend requires width/height > 0 and x+width <= 1, so anything that
 * clamps away to nothing is dropped rather than sent and rejected as a 422.
 */
export function toNormalizedBounds(
  box: Box,
  frame: Box,
): NormalizedBounds | null {
  if (frame.w <= 0 || frame.h <= 0) {
    return null;
  }

  const left = clamp01((box.x - frame.x) / frame.w);
  const top = clamp01((box.y - frame.y) / frame.h);
  const right = clamp01((box.x + box.w - frame.x) / frame.w);
  const bottom = clamp01((box.y + box.h - frame.y) / frame.h);

  const width = right - left;
  const height = bottom - top;
  if (width <= 0 || height <= 0) {
    return null;
  }

  return { x: left, y: top, width, height };
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.min(1, Math.max(0, value));
}

function readOwner(meta: unknown): ShapeOwner {
  const owner = (meta as { owner?: unknown } | null)?.owner;
  return owner === "ai" || owner === "system" ? owner : "student";
}

function richTextToPlainText(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const node = value as { type?: unknown; text?: unknown; content?: unknown };
  if (typeof node.text === "string") return node.text;
  if (node.type === "hardBreak") return "\n";
  const content = Array.isArray(node.content)
    ? node.content.map(richTextToPlainText).join("")
    : "";
  return `${content}${node.type === "paragraph" || node.type === "heading" ? "\n" : ""}`;
}

function readText(props: unknown): string | undefined {
  const text = (props as { text?: unknown } | null)?.text;
  if (typeof text === "string" && text.trim().length > 0) {
    return text;
  }

  const richText = (props as { richText?: unknown } | null)?.richText;
  const rendered = richTextToPlainText(richText).trim();
  return rendered.length > 0 ? rendered : undefined;
}

/** Structured companion to the image: what is on the canvas and who put it there. */
export function buildCanvasContext(
  editor: Editor,
  capture: CanvasCapture,
): CanvasContext {
  const shapes: CanvasShape[] = [];

  // Keep the structured canvas companion aligned with the pixels. Prior tutor
  // context travels through recent_interactions instead of AI-authored shapes.
  for (const id of capture.shapeIds) {
    const shape = editor.getShape(id);
    if (!shape) {
      continue;
    }

    const pageBounds = editor.getShapePageBounds(shape);
    shapes.push({
      id: shape.id,
      owner: readOwner(shape.meta),
      shape_type: shape.type,
      bounds: pageBounds ? toNormalizedBounds(pageBounds, capture.bounds) : null,
      text: readText(shape.props) ?? null,
    });
  }

  const viewport = editor.getViewportPageBounds();

  return {
    image_width: capture.width,
    image_height: capture.height,
    viewport: viewport
      ? {
          x: viewport.x,
          y: viewport.y,
          width: viewport.w,
          height: viewport.h,
          zoom: editor.getZoomLevel(),
        }
      : null,
    shapes,
  };
}
