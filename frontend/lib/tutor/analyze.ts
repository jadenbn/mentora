/**
 * One tutor interaction, end to end:
 * capture the student's work -> ask the backend -> draw the answer.
 */

import type { Editor } from "tldraw";
import { analyzeCanvas, submitWork } from "@/lib/api/api";
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
  signal?: AbortSignal;
  /** Supplied for a skill-attributed problem, so the server can record. */
  studentId?: string;
  sessionId?: string;
  /** Whiteboard supplies the progressive renderer; tests and other callers may render immediately. */
  renderActions?: (
    editor: Editor,
    actions: TutorResponse["canvas_actions"],
    context: RenderContext,
  ) => void | Promise<void>;
}

export async function runTutorAnalysis(
  options: TutorAnalysisOptions,
): Promise<TutorResponse> {
  const { editor, problem, studentId, sessionId } = options;
  const renderActions = options.renderActions ?? renderCanvasActions;

  // A canvas holding only the tutor's own earlier feedback has nothing of the
  // student's left to analyze, even though the page is not empty.
  const capture = await captureCanvasForAnalysis(editor);
  if (!capture) {
    if (options.mode !== "stuck" || !problem || hasStudentWork(editor)) {
      throw new EmptyCanvasError();
    }

    // A problem-only stuck request has no student image by design. Send the
    // structured problem without fabricating a provider image. /work always
    // requires an image, so this path never records an attempt either way.
    const bounds = editor.getCurrentPageBounds() ?? editor.getViewportPageBounds();
    const response = await analyzeCanvas({
      courseId: options.courseId,
      mode: options.mode,
      priorAnnotations: collectPriorAnnotations(editor, bounds),
      problem,
      signal: options.signal,
    });
    await renderActions(editor, response.canvas_actions, {
      bounds,
      interactionId: response.interaction_id,
    });
    return response;
  }

  const priorAnnotations = collectPriorAnnotations(editor, capture.bounds);

  // A skill-attributed problem goes through /work: the tutor grades and the
  // server records the attempt in one round trip. The browser deciding
  // `correct` for itself was the reason mastery could be forged. What the
  // server recorded is not surfaced here -- the engine has no UI.
  const response =
    problem?.skill && studentId && sessionId
      ? await submitWork({
          courseId: options.courseId,
          studentId,
          sessionId,
          problemId: problem.id,
          mode: options.mode,
          canvasImage: capture.blob,
          priorAnnotations,
          signal: options.signal,
        })
      : await analyzeCanvas({
          courseId: options.courseId,
          mode: options.mode,
          canvasImage: capture.blob,
          priorAnnotations,
          problem,
          signal: options.signal,
        });

  await renderActions(editor, response.canvas_actions, {
    bounds: capture.bounds,
    interactionId: response.interaction_id,
  });

  return response;
}
