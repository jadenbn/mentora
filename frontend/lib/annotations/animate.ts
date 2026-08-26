/**
 * Progressive reveal of tutor annotations, so feedback appears to be written
 * rather than pasted (ARCHITECTURE.md section 19).
 *
 * Two deliberate choices:
 *
 * - Frames are driven by setTimeout at a capped rate rather than rAF. iPad
 *   Safari is the primary target and 60fps document writes are the thing that
 *   falls over; a fixed 30fps also makes every test deterministic under fake
 *   timers.
 * - Every write uses history: "ignore". Without it a single animated
 *   annotation would bury the student's undo stack under hundreds of frames.
 */

// compressLegacySegments is not re-exported by the tldraw barrel, so tlschema
// is a declared dependency pinned to the same version.
import { compressLegacySegments } from "@tldraw/tlschema";
import { createShapeId } from "tldraw";
import type {
  Editor,
  JsonObject,
  TLDefaultColorStyle,
  TLDefaultSizeStyle,
  TLShapeId,
} from "tldraw";
import { strokeLength, type Stroke } from "@/lib/annotations/geometry";

export const DEFAULT_FPS = 30;
/** Pen speed in world units per second. */
export const DEFAULT_PEN_SPEED = 900;
/** Pause between one stroke finishing and the next starting. */
export const PEN_LIFT_MS = 90;

export interface AnimationHandle {
  /** Stop immediately, leaving whatever has been drawn so far in place. */
  cancel: () => void;
  /** Resolves when the animation finishes or is cancelled. */
  done: Promise<void>;
}

export interface StrokeAnimationOptions {
  meta?: Partial<JsonObject>;
  color?: TLDefaultColorStyle;
  size?: TLDefaultSizeStyle;
  fps?: number;
  penSpeed?: number;
  /** Called once per created shape, so callers can track what was drawn. */
  onShape?: (id: TLShapeId) => void;
}

interface Frame {
  run: () => void;
}

/**
 * A cancellable queue of frames, each separated by one tick. Keeping the
 * scheduling in one place means cancellation has a single place to check.
 */
function schedule(frames: Frame[], intervalMs: number): AnimationHandle {
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let resolve!: () => void;
  const done = new Promise<void>((r) => (resolve = r));

  let index = 0;
  const step = () => {
    timer = null;
    if (cancelled) {
      return;
    }
    if (index >= frames.length) {
      resolve();
      return;
    }
    frames[index++].run();
    timer = setTimeout(step, intervalMs);
  };

  timer = setTimeout(step, 0);

  return {
    cancel: () => {
      if (cancelled) {
        return;
      }
      cancelled = true;
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      resolve();
    },
    done,
  };
}

function write(editor: Editor, fn: () => void): void {
  // Animation frames are presentation, not student intent: keep them out of
  // the undo stack entirely.
  editor.run(fn, { history: "ignore" });
}

/** Draw a set of strokes in order, revealing each one point by point. */
export function animateStrokes(
  editor: Editor,
  strokes: Stroke[],
  options: StrokeAnimationOptions = {},
): AnimationHandle {
  const {
    meta = {},
    color = "red",
    size = "m",
    fps = DEFAULT_FPS,
    penSpeed = DEFAULT_PEN_SPEED,
    onShape,
  } = options;

  const intervalMs = 1000 / fps;
  const frames: Frame[] = [];

  for (const stroke of strokes) {
    if (stroke.length < 2) {
      continue;
    }

    const id = createShapeId();
    const origin = stroke[0];
    const local = stroke.map((p) => ({ x: p.x - origin.x, y: p.y - origin.y }));

    // Pace by length, so a long underline and a small tick feel like the same
    // hand moving rather than the same duration.
    const durationMs = (strokeLength(stroke) / penSpeed) * 1000;
    const frameCount = Math.max(2, Math.round(durationMs / intervalMs));

    frames.push({
      run: () =>
        write(editor, () => {
          editor.createShape({
            id,
            type: "draw",
            x: origin.x,
            y: origin.y,
            meta,
            props: {
              segments: compressLegacySegments([
                { type: "free", points: [local[0]] },
              ]),
              color,
              size,
              isComplete: false,
            },
          });
          onShape?.(id);
        }),
    });

    for (let frame = 1; frame <= frameCount; frame++) {
      const upto = Math.max(
        2,
        Math.ceil((local.length * frame) / frameCount),
      );
      const isLast = frame === frameCount;
      frames.push({
        run: () =>
          write(editor, () => {
            editor.updateShape({
              id,
              type: "draw",
              props: {
                segments: compressLegacySegments([
                  { type: "free", points: local.slice(0, upto) },
                ]),
                isComplete: isLast,
              },
            });
          }),
      });
    }

    // A beat between strokes reads as lifting the pen.
    const liftFrames = Math.round(PEN_LIFT_MS / intervalMs);
    for (let i = 0; i < liftFrames; i++) {
      frames.push({ run: () => {} });
    }
  }

  return schedule(frames, intervalMs);
}

/** A cancellable pause, so a script can breathe between beats. */
export function wait(ms: number): AnimationHandle {
  return schedule([{ run: () => {} }], ms);
}

/** Run animations one after another, cancellable as a unit. */
export function sequence(steps: (() => AnimationHandle)[]): AnimationHandle {
  let cancelled = false;
  let current: AnimationHandle | null = null;
  let resolve!: () => void;
  const done = new Promise<void>((r) => (resolve = r));

  const runNext = async (index: number): Promise<void> => {
    if (cancelled || index >= steps.length) {
      resolve();
      return;
    }
    current = steps[index]();
    await current.done;
    await runNext(index + 1);
  };

  void runNext(0);

  return {
    cancel: () => {
      cancelled = true;
      current?.cancel();
      resolve();
    },
    done,
  };
}
