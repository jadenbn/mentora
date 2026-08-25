/**
 * Canvas capture.
 *
 * Two jobs: export an image of the student's work, and report the world-space
 * rectangle that image covers, because the tutor answers in coordinates
 * normalized to it.
 *
 * The tutor's own annotations are deliberately excluded from the export. They
 * sit on the same canvas as the student's work, so leaving them in would let
 * the model read its own handwriting back and grade it. Their positions travel
 * separately, as prior annotations, so follow-up feedback still has context.
 */

import type { Box, Editor, TLShapeId } from "tldraw";
import { AI_SHAPE_OWNER } from "@/lib/annotations/renderCanvasActions";
import { SYSTEM_SHAPE_OWNER } from "@/lib/canvas/ownership";
import type { NormalizedBounds } from "@/types/tutor";

/** Keeps the upload well under the backend's 10 MB limit. */
const MAX_IMAGE_EDGE = 1280;

// Valid 1×1 transparent PNG used when a student asks for help before drawing.
// The problem itself travels separately as structured problem_context.
const EMPTY_CANVAS_PNG = new Uint8Array([
  137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 1,
  0, 0, 0, 1, 8, 6, 0, 0, 0, 31, 21, 196, 137, 0, 0, 0, 13, 73, 68, 65,
  84, 120, 156, 99, 96, 0, 0, 0, 2, 0, 1, 226, 33, 188, 51, 0, 0, 0, 0,
  73, 69, 78, 68, 174, 66, 96, 130,
]);

export interface CanvasCapture {
  blob: Blob;
  /** World-space rectangle the image covers. */
  bounds: Box;
}

/** A valid blank image for a problem-only tutor request. */
export function emptyCanvasForAnalysis(editor: Editor): CanvasCapture | null {
  const bounds = editor.getCurrentPageBounds() ?? editor.getViewportPageBounds();
  if (!bounds || bounds.w <= 0 || bounds.h <= 0) {
    return null;
  }
  return {
    blob: new Blob([EMPTY_CANVAS_PNG], { type: "image/png" }),
    bounds,
  };
}

function isTutorShape(editor: Editor, id: TLShapeId): boolean {
  return editor.getShape(id)?.meta?.owner === AI_SHAPE_OWNER;
}

function studentShapeIds(editor: Editor): TLShapeId[] {
  return [...editor.getCurrentPageShapeIds()].filter((id) => {
    const owner = editor.getShape(id)?.meta?.owner;
    return owner !== AI_SHAPE_OWNER && owner !== SYSTEM_SHAPE_OWNER;
  });
}

export async function captureCanvasForAnalysis(
  editor: Editor,
): Promise<CanvasCapture | null> {
  const shapeIds = studentShapeIds(editor);
  if (shapeIds.length === 0) {
    return null;
  }

  const bounds = editor.getCurrentPageBounds();
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

  return image?.blob ? { blob: image.blob, bounds } : null;
}

/**
 * Where the tutor has already written, normalized to the captured frame.
 *
 * Empty on a first interaction. Anything that falls outside the frame is
 * dropped rather than clamped to a misleading position.
 */
export function collectPriorAnnotations(
  editor: Editor,
  frame: Box,
): NormalizedBounds[] {
  const prior: NormalizedBounds[] = [];
  for (const id of editor.getCurrentPageShapeIds()) {
    if (!isTutorShape(editor, id)) {
      continue;
    }
    const shape = editor.getShape(id);
    const pageBounds = shape ? editor.getShapePageBounds(shape) : null;
    const normalized = pageBounds ? toNormalizedBounds(pageBounds, frame) : null;
    if (normalized) {
      prior.push(normalized);
    }
  }
  return prior;
}

/**
 * Normalize a world-space box against the captured frame.
 *
 * The backend requires width/height > 0 and x+width <= 1, so anything that
 * clamps away to nothing is dropped rather than sent and rejected as a 422.
 */
export function toNormalizedBounds(box: Box, frame: Box): NormalizedBounds | null {
  if (frame.w <= 0 || frame.h <= 0) {
    return null;
  }

  const left = clamp01((box.x - frame.x) / frame.w);
  const top = clamp01((box.y - frame.y) / frame.h);
  const width = clamp01((box.x + box.w - frame.x) / frame.w) - left;
  const height = clamp01((box.y + box.h - frame.y) / frame.h) - top;

  return width > 0 && height > 0 ? { x: left, y: top, width, height } : null;
}

function clamp01(value: number): number {
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
}
