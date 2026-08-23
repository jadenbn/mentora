/**
 * One tutor interaction, end to end:
 * capture canvas -> build structured context -> POST -> render annotations.
 */

import type { Editor } from "tldraw";
import { analyzeCanvas } from "@/lib/api/api";
import {
  buildCanvasContext,
  captureCanvasForAnalysis,
} from "@/lib/canvas/capture";
import { renderCanvasActions } from "@/lib/annotations/renderCanvasActions";
import type {
  ClientCapabilities,
  PriorTutorInteraction,
  ProblemContext,
  StudentModelSnapshot,
  TutorMode,
  TutorRequest,
  TutorResponse,
} from "@/types/tutor";

/**
 * What this frontend can actually draw. Declared honestly: "math" is omitted
 * and supports_latex is false because the renderer has no LaTeX support yet,
 * so the backend should not plan math actions.
 */
const CLIENT_CAPABILITIES: ClientCapabilities = {
  supported_actions: [
    "text",
    "arrow",
    "circle",
    "underline",
    "highlight",
    "check",
    "cross",
  ],
  supports_latex: false,
  supports_selection_crop: false,
};

export class EmptyCanvasError extends Error {
  constructor() {
    super("There is nothing on the canvas to analyze yet.");
    this.name = "EmptyCanvasError";
  }
}

export interface TutorAnalysisOptions {
  editor: Editor;
  mode: TutorMode;
  userId: string;
  courseId: string;
  sessionId: string;
  problemId: string;
  problem: ProblemContext;
  recentInteractions?: PriorTutorInteraction[];
  studentModel?: StudentModelSnapshot;
  signal?: AbortSignal;
}

export async function runTutorAnalysis(
  options: TutorAnalysisOptions,
): Promise<TutorResponse> {
  const { editor } = options;

  const capture = await captureCanvasForAnalysis(editor);
  if (!capture) {
    throw new EmptyCanvasError();
  }

  const request: TutorRequest = {
    schema_version: "1.0",
    request_id: crypto.randomUUID(),
    user_id: options.userId,
    course_id: options.courseId,
    session_id: options.sessionId,
    problem_id: options.problemId,
    mode: options.mode,
    trigger: "manual",
    problem: options.problem,
    canvas: buildCanvasContext(editor, capture),
    recent_interactions: options.recentInteractions ?? [],
    student_model: options.studentModel ?? null,
    locale: "en",
    client_capabilities: CLIENT_CAPABILITIES,
  };

  const response = await analyzeCanvas({
    request,
    canvasImage: capture.blob,
    signal: options.signal,
  });

  renderCanvasActions(editor, response.canvas_actions, {
    bounds: capture.bounds,
    interactionId: response.interaction_id,
  });

  return response;
}
