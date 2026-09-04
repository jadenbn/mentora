/**
 * One tutor interaction, end to end:
 * capture the student's work -> ask the backend -> draw the answer.
 */

import type { Editor } from "tldraw";
import { analyzeCanvas } from "@/lib/api/api";
import {
  captureCanvasForAnalysis,
  collectPriorAnnotations,
  hasStudentWork,
} from "@/lib/canvas/capture";
import {
  renderCanvasActions,
  type RenderContext,
} from "@/lib/annotations/renderCanvasActions";
import type { TutorMode, TutorResponse } from "@/types/tutor";
import type { ProblemContext } from "@/types/domain";

const IMAGE_URL_TTL_MS = 5 * 60 * 1_000;

/** Log the exact blob sent in canvas_image without persisting it to disk. */
function logSentImage(blob: Blob): void {
  if (
    process.env.NODE_ENV === "production" ||
    typeof URL === "undefined" ||
    typeof URL.createObjectURL !== "function"
  ) {
    return;
  }
  const imageUrl = URL.createObjectURL(blob);
  console.log("[tutor] image sent for Gemini analysis");
  console.log(imageUrl);
  setTimeout(() => URL.revokeObjectURL(imageUrl), IMAGE_URL_TTL_MS);
}

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
  problem?: ProblemContext;
  /** What the student asked out loud, when they used the microphone. */
  transcript?: string;
  signal?: AbortSignal;
  /** Whiteboard supplies the progressive renderer; tests and other callers may render immediately. */
  renderActions?: (
    editor: Editor,
    actions: TutorResponse["canvas_actions"],
    context: RenderContext,
  ) => void | Promise<void>;
  /** Called when the provider response arrives, before presentation animation. */
  onResponse?: (
    response: TutorResponse,
    context: RenderContext,
    snapshot: unknown,
  ) => void;
}

export async function runTutorAnalysis(
  options: TutorAnalysisOptions,
): Promise<TutorResponse> {
  const { editor } = options;
  const renderActions = options.renderActions ?? renderCanvasActions;
  const snapshot = editor.getSnapshot().document;

  // A canvas holding only the tutor's own earlier feedback has nothing of the
  // student's left to analyze, even though the page is not empty.
  const capture = await captureCanvasForAnalysis(editor);
  if (!capture) {
    if (options.mode !== "stuck" || !options.problem || hasStudentWork(editor)) {
      throw new EmptyCanvasError();
    }

    // A problem-only stuck request has no student image by design. Send the
    // structured problem without fabricating a provider image.
    const bounds = editor.getCurrentPageBounds() ?? editor.getViewportPageBounds();
    const response = await analyzeCanvas({
      mode: options.mode,
      courseId: options.courseId,
      priorAnnotations: collectPriorAnnotations(editor, bounds),
      problem: options.problem,
      transcript: options.transcript,
      signal: options.signal,
    });
    const context = {
      bounds,
      interactionId: response.interaction_id,
    };
    options.onResponse?.(response, context, snapshot);
    await renderActions(editor, response.canvas_actions, context);
    return response;
  }

  logSentImage(capture.blob);
  const response = await analyzeCanvas({
    courseId: options.courseId,
    mode: options.mode,
    canvasImage: capture.blob,
    priorAnnotations: collectPriorAnnotations(editor, capture.bounds),
    problem: options.problem,
    transcript: options.transcript,
    signal: options.signal,
  });

  const context = {
    bounds: capture.bounds,
    interactionId: response.interaction_id,
  };
  options.onResponse?.(response, context, snapshot);
  await renderActions(editor, response.canvas_actions, context);

  return response;
}
