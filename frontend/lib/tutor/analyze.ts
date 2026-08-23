/**
 * One tutor interaction, end to end:
 * capture the student's work -> ask the backend -> draw the answer.
 */

import type { Editor } from "tldraw";
import { analyzeCanvas } from "@/lib/api/api";
import {
  captureCanvasForAnalysis,
  collectPriorAnnotations,
} from "@/lib/canvas/capture";
import { renderCanvasActions } from "@/lib/annotations/renderCanvasActions";
import type { TutorMode, TutorResponse } from "@/types/tutor";

export class EmptyCanvasError extends Error {
  constructor() {
    super("There is nothing on the canvas to analyze yet.");
    this.name = "EmptyCanvasError";
  }
}

export interface TutorAnalysisOptions {
  editor: Editor;
  mode: TutorMode;
  courseId: string;
  signal?: AbortSignal;
}

export async function runTutorAnalysis(
  options: TutorAnalysisOptions,
): Promise<TutorResponse> {
  const { editor } = options;

  // A canvas holding only the tutor's own earlier feedback has nothing of the
  // student's left to analyze, even though the page is not empty.
  const capture = await captureCanvasForAnalysis(editor);
  if (!capture) {
    throw new EmptyCanvasError();
  }

  const response = await analyzeCanvas({
    courseId: options.courseId,
    mode: options.mode,
    canvasImage: capture.blob,
    priorAnnotations: collectPriorAnnotations(editor, capture.bounds),
    signal: options.signal,
  });

  renderCanvasActions(editor, response.canvas_actions, {
    bounds: capture.bounds,
    interactionId: response.interaction_id,
  });

  return response;
}
