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

import { Box } from "tldraw";
import type { Editor, TLShapeId } from "tldraw";
import { AI_SHAPE_OWNER } from "@/lib/annotations/renderCanvasActions";
import { SYSTEM_SHAPE_OWNER } from "@/lib/canvas/ownership";
import type { NormalizedBounds } from "@/types/tutor";

/** Keeps the upload well under the backend's 10 MB limit. */
const MAX_IMAGE_EDGE = 1280;
const ANALYSIS_PADDING = 96;
const MIN_ANALYSIS_WIDTH = 720;
const MIN_ANALYSIS_HEIGHT = 480;

// Valid 1×1 transparent PNG used when a student asks for help before drawing.
// The problem itself travels separately as structured problem_context.

export interface CanvasCapture {
  blob: Blob;
  /** World-space rectangle the image covers. */
  bounds: Box;
  /** Raster dimensions after tldraw has rendered the image. */
  imageWidth: number;
  imageHeight: number;
  /** Student rectangle before padding/minimum-size expansion. */
  studentBounds: Box;
  /** Frame content, including prior tutor marks when present. */
  contentBounds: Box;
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

/** Bounds of student work, ignoring the system problem and tutor marks. */
export function studentContentBounds(editor: Editor): Box | null {
  return boundsForShapeIds(editor, studentShapeIds(editor));
}

/** Bounds used for analysis: student work plus prior tutor marks. */
function analysisContentBounds(editor: Editor): Box | null {
  const ids = [...editor.getCurrentPageShapeIds()].filter((id) => {
    return editor.getShape(id)?.meta?.owner !== SYSTEM_SHAPE_OWNER;
  });
  return boundsForShapeIds(editor, ids);
}

function boundsForShapeIds(editor: Editor, ids: TLShapeId[]): Box | null {
  let result: Box | null = null;
  for (const id of ids) {
    const shape = editor.getShape(id);
    const bounds = shape ? editor.getShapePageBounds(shape) : null;
    if (!bounds || bounds.w <= 0 || bounds.h <= 0) continue;
    result = result
      ? result.expand(bounds)
      : new Box(bounds.x, bounds.y, bounds.w, bounds.h);
  }
  return result;
}

function analysisFrame(content: Box): Box {
  const padded = new Box(
    content.x - ANALYSIS_PADDING,
    content.y - ANALYSIS_PADDING,
    content.w + ANALYSIS_PADDING * 2,
    content.h + ANALYSIS_PADDING * 2,
  );
  const width = Math.max(padded.w, MIN_ANALYSIS_WIDTH);
  const height = Math.max(padded.h, MIN_ANALYSIS_HEIGHT);
  return new Box(
    padded.x - (width - padded.w) / 2,
    padded.y - (height - padded.h) / 2,
    width,
    height,
  );
}

export function hasStudentWork(editor: Editor): boolean {
  return studentShapeIds(editor).length > 0;
}

export async function captureCanvasForAnalysis(
  editor: Editor,
): Promise<CanvasCapture | null> {
  const shapeIds = studentShapeIds(editor);
  if (shapeIds.length === 0) {
    return null;
  }

  const studentBounds = studentContentBounds(editor);
  const contentBounds = analysisContentBounds(editor);
  if (!studentBounds || !contentBounds) return null;
  const bounds = analysisFrame(contentBounds);

  const scale = Math.min(1, MAX_IMAGE_EDGE / Math.max(bounds.w, bounds.h));
  const image = await editor.toImage(shapeIds, {
    format: "png",
    background: true,
    padding: 0,
    bounds,
    scale,
  });

  return image?.blob
    ? {
        blob: image.blob,
        bounds,
        imageWidth: image.width,
        imageHeight: image.height,
        studentBounds,
        contentBounds,
      }
    : null;
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
