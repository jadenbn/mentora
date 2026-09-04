import { useCallback, useEffect, useRef, useState } from "react";
import type { Editor } from "tldraw";
import { animateCanvasActions } from "@/lib/annotations/animateActions";
import type { AnimationHandle } from "@/lib/annotations/animate";
import {
  clearAiShapes,
  renderCanvasActions,
  type RenderContext,
} from "@/lib/annotations/renderCanvasActions";
import { hasStudentWork as getHasStudentCanvasWork } from "@/lib/canvas/capture";
import {
  loadCanvas,
  loadCanvasSnapshot,
  saveCanvas,
  startAutosave,
} from "@/lib/canvas/persistence";
import {
  ensureVerticalPage,
  growVerticalPage,
  removeStudentShapesOutsidePage,
  positionVerticalPageCamera,
} from "@/lib/canvas/verticalPage";
import { ensureProblemShape } from "@/lib/problems/renderProblem";
import { touchSpace } from "@/lib/spaces/store";
import { EmptyCanvasError, runTutorAnalysis } from "@/lib/tutor/analyze";
import {
  appendFeedbackLayer,
  emptyFeedbackHistory,
  loadFeedbackHistory,
  moveFeedbackLayer,
  saveFeedbackHistory,
  toggleFeedback,
  type FeedbackHistory,
  type FeedbackLayer,
} from "@/lib/tutor/feedbackHistory";
import type { ProblemContext } from "@/types/domain";
import type { CanvasAction, TutorMode, TutorResponse } from "@/types/tutor";

interface WhiteboardSessionOptions {
  spaceId: string;
  courseId: string;
  problem?: ProblemContext;
}

export function useWhiteboardSession({
  spaceId,
  courseId,
  problem,
}: WhiteboardSessionOptions) {
  const editor = useRef<Editor | null>(null);
  const liveSnapshot = useRef<unknown | null>(null);
  const disposeAutosave = useRef<(() => void) | null>(null);
  const disposeWorkListener = useRef<(() => void) | null>(null);
  const animation = useRef<AnimationHandle | null>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const feedbackWarningTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [justSaved, setJustSaved] = useState(false);
  const [busyMode, setBusyMode] = useState<TutorMode | null>(null);
  const [isThinking, setIsThinking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasStudentCanvasWork, setHasStudentCanvasWork] = useState(false);
  const [feedbackHistory, setFeedbackHistory] = useState<FeedbackHistory>(() =>
    emptyFeedbackHistory(),
  );
  const [feedbackWarning, setFeedbackWarning] = useState<string | null>(null);

  const renderStoredLayer = useCallback(
    (currentEditor: Editor, layer: FeedbackLayer | null, visible: boolean) => {
      animation.current?.cancel();
      animation.current = null;
      clearAiShapes(currentEditor);
      if (layer && visible) {
        renderCanvasActions(currentEditor, layer.response.canvas_actions, {
          bounds: layer.bounds,
          interactionId: layer.response.interaction_id,
        });
      }
    },
    [],
  );

  const storeFeedbackHistory = useCallback(
    (next: FeedbackHistory) => {
      setFeedbackHistory(next);
      saveFeedbackHistory(spaceId, next);
    },
    [spaceId],
  );

  const showFeedbackWarning = useCallback(() => {
    setFeedbackWarning("Earlier feedback was removed to keep the last 10 layers.");
    if (feedbackWarningTimer.current !== null) {
      clearTimeout(feedbackWarningTimer.current);
    }
    feedbackWarningTimer.current = setTimeout(() => {
      feedbackWarningTimer.current = null;
      setFeedbackWarning(null);
    }, 3_500);
  }, []);

  const renderTutorActions = useCallback(
    (
      currentEditor: Editor,
      actions: CanvasAction[],
      context: RenderContext,
    ): Promise<void> => {
      animation.current?.cancel();
      clearAiShapes(currentEditor);
      setIsThinking(false);
      const next = animateCanvasActions(currentEditor, actions, context);
      animation.current = next;
      return next.done.then(() => {
        if (animation.current === next) {
          animation.current = null;
        }
      });
    },
    [],
  );

  const handleTutorResponse = useCallback(
    (
      mode: TutorMode,
      response: TutorResponse,
      context: RenderContext,
      snapshot: unknown,
    ) => {
      const layer: FeedbackLayer = {
        id: response.interaction_id,
        mode,
        createdAt: new Date().toISOString(),
        bounds: {
          x: context.bounds.x,
          y: context.bounds.y,
          w: context.bounds.w,
          h: context.bounds.h,
        },
        snapshot,
        response,
      };
      const result = appendFeedbackLayer(feedbackHistory, layer);
      storeFeedbackHistory(result.history);
      if (result.dropped) {
        showFeedbackWarning();
      }
    },
    [feedbackHistory, showFeedbackWarning, storeFeedbackHistory],
  );

  const flashSaved = useCallback(() => {
    setJustSaved(true);
    if (savedTimer.current !== null) {
      clearTimeout(savedTimer.current);
    }
    savedTimer.current = setTimeout(() => {
      savedTimer.current = null;
      setJustSaved(false);
    }, 1_600);
  }, []);

  const handleMoveFeedback = useCallback(
    (delta: -1 | 1) => {
      const next = moveFeedbackLayer(feedbackHistory, delta);
      if (next === feedbackHistory) return;
      const layer = next.layers[next.activeIndex] ?? null;
      const currentEditor = editor.current;
      if (!currentEditor || !layer) return;

      const latestIndex = feedbackHistory.layers.length - 1;
      const leavingLive = feedbackHistory.activeIndex === latestIndex;
      const returningToLive = next.activeIndex === latestIndex;

      if (leavingLive) {
        liveSnapshot.current = currentEditor.getSnapshot().document;
        saveCanvas(currentEditor, spaceId);
      }

      if (returningToLive) {
        if (
          liveSnapshot.current !== null &&
          !loadCanvasSnapshot(currentEditor, liveSnapshot.current)
        ) {
          return;
        }
        liveSnapshot.current = null;
      } else if (!loadCanvasSnapshot(currentEditor, layer.snapshot)) {
        return;
      }

      if (leavingLive) {
        disposeAutosave.current?.();
        disposeAutosave.current = null;
      }

      currentEditor.updateInstanceState({ isReadonly: !returningToLive });
      renderStoredLayer(currentEditor, layer, next.visible);
      storeFeedbackHistory(next);
      if (returningToLive) {
        disposeAutosave.current = startAutosave(currentEditor, spaceId, {
          onSave: () => {
            touchSpace(spaceId);
            flashSaved();
          },
        });
      }
    },
    [feedbackHistory, flashSaved, renderStoredLayer, spaceId, storeFeedbackHistory],
  );

  const handleToggleFeedback = useCallback(() => {
    const next = toggleFeedback(feedbackHistory);
    if (next === feedbackHistory) return;
    storeFeedbackHistory(next);
    const layer = next.layers[next.activeIndex] ?? null;
    if (editor.current) {
      renderStoredLayer(editor.current, layer, next.visible);
    }
  }, [feedbackHistory, renderStoredLayer, storeFeedbackHistory]);

  const runAnalysis = useCallback(
    async (mode: TutorMode, transcript?: string) => {
      const current = editor.current;
      if (!current || busyMode !== null) {
        return;
      }

      setBusyMode(mode);
      setIsThinking(true);
      setError(null);

      try {
        await runTutorAnalysis({
          editor: current,
          mode,
          courseId,
          problem,
          transcript,
          renderActions: renderTutorActions,
          onResponse: (response, context, snapshot) =>
            handleTutorResponse(mode, response, context, snapshot),
        });
      } finally {
        animation.current = null;
        setIsThinking(false);
        setBusyMode(null);
      }
    },
    [busyMode, courseId, handleTutorResponse, problem, renderTutorActions],
  );

  const handleAnalyze = useCallback(
    (mode: TutorMode) => {
      void runAnalysis(mode).catch((caught) => {
        setError(
          caught instanceof EmptyCanvasError || caught instanceof Error
            ? caught.message
            : "The tutor request failed.",
        );
      });
    },
    [runAnalysis],
  );

  useEffect(() => {
    return () => {
      disposeAutosave.current?.();
      disposeAutosave.current = null;
      disposeWorkListener.current?.();
      disposeWorkListener.current = null;
      animation.current?.cancel();
      animation.current = null;
      setIsThinking(false);
      if (feedbackWarningTimer.current !== null) {
        clearTimeout(feedbackWarningTimer.current);
        feedbackWarningTimer.current = null;
      }
      if (savedTimer.current !== null) {
        clearTimeout(savedTimer.current);
        savedTimer.current = null;
      }
    };
  }, [spaceId]);

  const handleMount = useCallback(
    (mountedEditor: Editor) => {
      editor.current = mountedEditor;
      mountedEditor.updateInstanceState({ isGridMode: true });
      let documentChanged = loadCanvas(mountedEditor, spaceId);
      documentChanged = ensureVerticalPage(mountedEditor) || documentChanged;
      positionVerticalPageCamera(mountedEditor);
      const restoredFeedback = loadFeedbackHistory(spaceId);
      setFeedbackHistory(restoredFeedback);

      const updateStudentWork = () => {
        const next = getHasStudentCanvasWork(mountedEditor);
        setHasStudentCanvasWork((current) => (current === next ? current : next));
        growVerticalPage(mountedEditor);
        removeStudentShapesOutsidePage(mountedEditor);
      };
      updateStudentWork();
      disposeWorkListener.current?.();
      disposeWorkListener.current = mountedEditor.store.listen(updateStudentWork);

      if (problem && ensureProblemShape(mountedEditor, problem)) {
        documentChanged = true;
      }
      if (documentChanged) {
        saveCanvas(mountedEditor, spaceId);
      }
      liveSnapshot.current = mountedEditor.getSnapshot().document;

      const restoredLayer = restoredFeedback.layers[restoredFeedback.activeIndex] ?? null;
      const isHistorical =
        restoredLayer !== null &&
        restoredFeedback.activeIndex < restoredFeedback.layers.length - 1;
      if (isHistorical && restoredLayer) {
        loadCanvasSnapshot(mountedEditor, restoredLayer.snapshot);
      }
      mountedEditor.updateInstanceState({ isReadonly: isHistorical });
      renderStoredLayer(mountedEditor, restoredLayer, restoredFeedback.visible);
      if (!isHistorical) {
        disposeAutosave.current?.();
        disposeAutosave.current = startAutosave(mountedEditor, spaceId, {
          onSave: () => {
            touchSpace(spaceId);
            flashSaved();
          },
        });
      }
    },
    [flashSaved, problem, renderStoredLayer, spaceId],
  );

  return {
    busyMode,
    error,
    feedbackHistory,
    feedbackWarning,
    handleAnalyze,
    handleMount,
    handleMoveFeedback,
    handleToggleFeedback,
    hasStudentCanvasWork,
    isThinking,
    justSaved,
    runAnalysis,
  };
}
