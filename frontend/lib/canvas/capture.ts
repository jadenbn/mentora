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
  // Previous tutor feedback stays visible and persistent on the whiteboard,
  // but must not be baked into the next vision request. Otherwise the model
  // can mistake or reinforce its own annotations when they cover student work.
  const shapeIds = [...editor.getCurrentPageShapeIds()].filter((id) => {
    const shape = editor.getShape(id);
    return shape ? readOwner(shape.meta) !== "ai" : false;
  });
  if (shapeIds.length === 0) {
    return null;
  }

  const bounds = editor.getShapesPageBounds(shapeIds);
  if (!bounds || bounds.w <= 0 || bounds.h <= 0) {
    return null;
  }

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
  if (owner === "ai" || owner === "system") {
    return owner;
  }
  return "student";
}

function readText(props: unknown): string | undefined {
  const text = (props as { text?: unknown } | null)?.text;
  return typeof text === "string" && text.length > 0 ? text : undefined;
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
