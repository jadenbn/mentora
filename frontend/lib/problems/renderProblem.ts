/** Render structured problem data as one durable system-owned canvas shape. */

import { createShapeId, toRichText } from "tldraw";
import type { Editor } from "tldraw";
import type { Problem } from "@/types/domain";

export const SYSTEM_SHAPE_OWNER = "system";

export function ensureProblemShape(editor: Editor, problem: Problem): boolean {
  for (const id of editor.getCurrentPageShapeIds()) {
    const shape = editor.getShape(id);
    if (
      shape?.meta?.owner === SYSTEM_SHAPE_OWNER &&
      shape.meta.problemId === problem.id
    ) {
      return false;
    }
  }

  const viewport = editor.getViewportPageBounds();
  editor.createShape({
    id: createShapeId(`system-${problem.id}`),
    type: "note",
    x: viewport.x + 48,
    y: viewport.y + 48,
    isLocked: true,
    meta: { owner: SYSTEM_SHAPE_OWNER, problemId: problem.id },
    props: {
      richText: toRichText(`Question\n\n${problem.prompt}`),
      color: "light-blue",
      labelColor: "black",
      font: "sans",
      size: "m",
      align: "start",
      verticalAlign: "start",
    },
  });
  return true;
}
