/** Migration helpers for the retired system-owned problem note. */

import type { Editor, TLShapeId } from "tldraw";
import { SYSTEM_SHAPE_OWNER } from "@/lib/canvas/ownership";

/** Kept as a compatibility export; ownership is defined centrally. */
export { SYSTEM_SHAPE_OWNER } from "@/lib/canvas/ownership";

/**
 * Remove only the old locked note for this problem.
 *
 * The canonical problem remains on the Space record and is now rendered in a
 * pinned, typeset card. Other system-owned canvas content is left untouched.
 */
export function removeLegacyProblemShape(
  editor: Editor,
  problemId: string,
): boolean {
  const legacy: TLShapeId[] = [];
  for (const id of editor.getCurrentPageShapeIds()) {
    const shape = editor.getShape(id);
    if (
      shape?.meta?.owner === SYSTEM_SHAPE_OWNER &&
      shape.meta.problemId === problemId
    ) {
      legacy.push(id);
    }
  }

  if (legacy.length === 0) {
    return false;
  }
  editor.deleteShapes(legacy);
  return true;
}
