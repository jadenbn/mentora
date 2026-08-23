/**
 * Normalized-to-world conversion and the stroke paths the animated renderer
 * draws. Shared by both renderers so the coordinate arithmetic lives in exactly
 * one place (ARCHITECTURE.md section 19).
 */

import type { Box } from "tldraw";
import type { NormalizedBounds, NormalizedPoint } from "@/types/tutor";

export interface Vec2 {
  x: number;
  y: number;
}

/** One continuous pen stroke. A shape may need several. */
export type Stroke = Vec2[];

export interface WorldRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function toWorldPoint(point: NormalizedPoint, frame: Box): Vec2 {
  return {
    x: frame.x + point.x * frame.w,
    y: frame.y + point.y * frame.h,
  };
}

export function toWorldRect(target: NormalizedBounds, frame: Box): WorldRect {
  return {
    x: frame.x + target.x * frame.w,
    y: frame.y + target.y * frame.h,
    w: Math.max(1, target.width * frame.w),
    h: Math.max(1, target.height * frame.h),
  };
}

/**
 * A small deterministic wobble, so a drawn circle looks sketched rather than
 * plotted. Seeded from the action id so the same annotation always renders the
 * same way, and so tests can pin it.
 */
export function makeJitter(seed: string, amount: number) {
  let state = 0;
  for (let i = 0; i < seed.length; i++) {
    state = (state * 31 + seed.charCodeAt(i)) >>> 0;
  }
  return () => {
    // Numerical Recipes LCG: cheap, deterministic, good enough for wobble.
    state = (state * 1664525 + 1013904223) >>> 0;
    return ((state / 0xffffffff) * 2 - 1) * amount;
  };
}

/** An ellipse inscribed in the rect, opened slightly like a hand-drawn loop. */
export function ellipseStroke(rect: WorldRect, jitter: () => number): Stroke {
  const cx = rect.x + rect.w / 2;
  const cy = rect.y + rect.h / 2;
  const rx = rect.w / 2;
  const ry = rect.h / 2;
  const steps = 48;
  // Overshoot slightly past a full turn: people rarely close a circle exactly.
  const sweep = Math.PI * 2 * 1.04;
  const start = -Math.PI * 0.35;

  const points: Stroke = [];
  for (let i = 0; i <= steps; i++) {
    const angle = start + (sweep * i) / steps;
    points.push({
      x: cx + Math.cos(angle) * rx + jitter(),
      y: cy + Math.sin(angle) * ry + jitter(),
    });
  }
  return points;
}

export function lineStroke(
  from: Vec2,
  to: Vec2,
  jitter: () => number,
  steps = 12,
): Stroke {
  const points: Stroke = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    points.push({
      x: from.x + (to.x - from.x) * t + (i === 0 || i === steps ? 0 : jitter()),
      y: from.y + (to.y - from.y) * t + (i === 0 || i === steps ? 0 : jitter()),
    });
  }
  return points;
}

/** Underline along the bottom edge of the target. */
export function underlineStrokes(rect: WorldRect, jitter: () => number): Stroke[] {
  const y = rect.y + rect.h;
  return [lineStroke({ x: rect.x, y }, { x: rect.x + rect.w, y }, jitter, 16)];
}

/** A tick, drawn as one stroke: short down-right, then long up-right. */
export function checkStrokes(rect: WorldRect, jitter: () => number): Stroke[] {
  const size = Math.min(rect.w, rect.h) || 24;
  const originX = rect.x + rect.w;
  const originY = rect.y;
  const elbow = { x: originX + size * 0.35, y: originY + size * 0.75 };
  return [
    [
      ...lineStroke({ x: originX, y: originY + size * 0.4 }, elbow, jitter, 6),
      ...lineStroke(elbow, { x: originX + size * 0.95, y: originY }, jitter, 8).slice(1),
    ],
  ];
}

/** A cross, drawn as two separate strokes with a pen lift between them. */
export function crossStrokes(rect: WorldRect, jitter: () => number): Stroke[] {
  const size = Math.min(rect.w, rect.h) || 24;
  const x = rect.x + rect.w;
  const y = rect.y;
  return [
    lineStroke({ x, y }, { x: x + size, y: y + size }, jitter, 8),
    lineStroke({ x: x + size, y }, { x, y: y + size }, jitter, 8),
  ];
}

/** Total pen distance, used to pace a stroke at a constant speed. */
export function strokeLength(stroke: Stroke): number {
  let total = 0;
  for (let i = 1; i < stroke.length; i++) {
    total += Math.hypot(stroke[i].x - stroke[i - 1].x, stroke[i].y - stroke[i - 1].y);
  }
  return total;
}
