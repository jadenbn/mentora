"use client";

import dynamic from "next/dynamic";
import { Palette as PaletteIcon } from "lucide-react";
import { createPortal } from "react-dom";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowToolbarItem,
  DefaultStylePanel,
  DrawToolbarItem,
  Editor,
  EraserToolbarItem,
  HandToolbarItem,
  HighlightToolbarItem,
  RectangleToolbarItem,
  SelectToolbarItem,
  StylePanelColorPicker,
  StylePanelDashPicker,
  StylePanelFillPicker,
  StylePanelOpacityPicker,
  StylePanelSection,
  StylePanelSizePicker,
  TextToolbarItem,
  TldrawUiMenuContextProvider,
  TldrawUiToolbar,
  TldrawUiToolbarButton,
  useEditor,
  useValue,
} from "tldraw";
import { SaveIndicator } from "@/features/whiteboard/SaveIndicator";
import { TutorControls } from "@/features/tutor/TutorControls";
import { TutorFeedbackBar } from "@/features/tutor/TutorFeedbackBar";
import { animateCanvasActions } from "@/lib/annotations/animateActions";
import type { AnimationHandle } from "@/lib/annotations/animate";
import {
  clearAiShapes,
  renderCanvasActions,
} from "@/lib/annotations/renderCanvasActions";
import { hasStudentWork as getHasStudentCanvasWork } from "@/lib/canvas/capture";
import { loadCanvas, startAutosave } from "@/lib/canvas/persistence";
import { saveCanvas } from "@/lib/canvas/persistence";
import { ProblemShapeProvider, ProblemShapeUtil } from "@/lib/problems/ProblemShape";
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
import type {
  CanvasAction,
  TutorMode,
  TutorResponse,
} from "@/types/tutor";
import type { RenderContext } from "@/lib/annotations/renderCanvasActions";

const Tldraw = dynamic(() => import("tldraw").then((module) => module.Tldraw), {
  ssr: false,
});

function PaletteOptions() {
  const editor = useEditor();
  const [hasSelection, setHasSelection] = useState(
    () => editor.getSelectedShapeIds().length > 0,
  );

  useEffect(() => {
    const updateSelection = () => {
      const next = editor.getSelectedShapeIds().length > 0;
      setHasSelection((current) => (current === next ? current : next));
    };
    updateSelection();
    return editor.store.listen(updateSelection);
  }, [editor]);

  return (
    <div className="sidebar-style-panel w-52 rounded-xl border border-slate-200 bg-white p-2 shadow-xl">
      <DefaultStylePanel isMobile>
        <StylePanelSection>
          <StylePanelColorPicker />
          <StylePanelOpacityPicker />
        </StylePanelSection>
        {hasSelection ? (
          <StylePanelSection>
            <StylePanelFillPicker />
            <StylePanelDashPicker />
          </StylePanelSection>
        ) : null}
        <StylePanelSection>
          <StylePanelSizePicker />
        </StylePanelSection>
      </DefaultStylePanel>
    </div>
  );
}

function CanvasToolbar() {
  const editor = useEditor();
  const currentTool = useValue(
    "canvas-toolbar-tool",
    () => editor.getCurrentToolId(),
    [editor],
  );
  const paletteAvailable = currentTool !== "eraser";
  const [paletteOpen, setPaletteOpen] = useState(false);
  const showPalette = paletteOpen && paletteAvailable;

  return (
    <>
      <TldrawUiToolbar
        className="absolute! left-4! top-1/2! z-40! -translate-y-1/2!"
        label="Drawing tools"
        orientation="vertical"
        tooltipSide="right"
      >
        <TldrawUiMenuContextProvider sourceId="toolbar" type="toolbar">
          <SelectToolbarItem />
          <HandToolbarItem />
          <DrawToolbarItem />
          <HighlightToolbarItem />
          <TextToolbarItem />
          <ArrowToolbarItem />
          <RectangleToolbarItem />
          <EraserToolbarItem />
          <TldrawUiToolbarButton
            className="hover:cursor-grab"
            disabled={!paletteAvailable}
            isActive={showPalette}
            onClick={() => setPaletteOpen((current) => !current)}
            title={showPalette ? "Close palette" : "Open palette"}
            type="tool"
            tooltip={showPalette ? "Close palette" : "Open palette"}
          >
            <PaletteIcon aria-hidden="true" className="size-4" />
          </TldrawUiToolbarButton>
        </TldrawUiMenuContextProvider>
      </TldrawUiToolbar>
      {showPalette ? (
        <button
          aria-label="Close palette"
          className="fixed inset-0 z-30 cursor-default"
          onClick={() => setPaletteOpen(false)}
          type="button"
        />
      ) : null}
      {showPalette ? (
        <div className="absolute left-16 top-1/2 z-50 -translate-y-1/2">
          <PaletteOptions />
        </div>
      ) : null}
    </>
  );
}

function ThinkingPill() {
  return (
    <div
      aria-live="polite"
      className="pointer-events-none mx-auto w-fit rounded-full border border-slate-200 bg-white/80 px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm backdrop-blur-sm"
      role="status"
    >
      Thinking
      <span aria-hidden="true" className="ml-1 inline-flex gap-0.5">
        <span className="animate-bounce [animation-delay:-0.2s] motion-reduce:animate-none">.</span>
        <span className="animate-bounce [animation-delay:-0.1s] motion-reduce:animate-none">.</span>
        <span className="animate-bounce motion-reduce:animate-none">.</span>
      </span>
    </div>
  );
}

export function Whiteboard({
  spaceId,
  courseId,
  problem,
  feedbackHost,
  thinkingHost,
}: {
  spaceId: string;
  courseId: string;
  problem?: ProblemContext;
  feedbackHost?: HTMLElement | null;
  thinkingHost?: HTMLElement | null;
}) {
  const editor = useRef<Editor | null>(null);
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
    (mode: TutorMode, response: TutorResponse, context: RenderContext) => {
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

  const handleMoveFeedback = useCallback(
    (delta: -1 | 1) => {
      const next = moveFeedbackLayer(feedbackHistory, delta);
      if (next === feedbackHistory) return;
      storeFeedbackHistory(next);
      const layer = next.layers[next.activeIndex] ?? null;
      if (editor.current) {
        renderStoredLayer(editor.current, layer, next.visible);
      }
    },
    [feedbackHistory, renderStoredLayer, storeFeedbackHistory],
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

  const handleAnalyze = useCallback(
    async (mode: TutorMode) => {
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
          renderActions: renderTutorActions,
          onResponse: (response, context) =>
            handleTutorResponse(mode, response, context),
        });
      } catch (caught) {
        setError(
          caught instanceof EmptyCanvasError || caught instanceof Error
            ? caught.message
            : "The tutor request failed.",
        );
      } finally {
        animation.current = null;
        setIsThinking(false);
        setBusyMode(null);
      }
    },
    [busyMode, courseId, handleTutorResponse, problem, renderTutorActions],
  );

  // Autosave outlives any single render, so tear it down when the space closes.
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

  /** Flash the indicator, restarting the countdown if saves come back to back. */
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

  const handleMount = useCallback(
    (mountedEditor: Editor) => {
      editor.current = mountedEditor;
      mountedEditor.updateInstanceState({ isGridMode: true });
      // Restore before the student can draw, so their work is never briefly
      // absent and then overwritten by an autosave of an empty canvas.
      loadCanvas(mountedEditor, spaceId);
      const restoredFeedback = loadFeedbackHistory(spaceId);
      setFeedbackHistory(restoredFeedback);
      const updateStudentWork = () => {
        const next = getHasStudentCanvasWork(mountedEditor);
        setHasStudentCanvasWork((current) => (current === next ? current : next));
      };
      updateStudentWork();
      disposeWorkListener.current?.();
      disposeWorkListener.current = mountedEditor.store.listen(updateStudentWork);
      if (problem && ensureProblemShape(mountedEditor, problem)) {
        saveCanvas(mountedEditor, spaceId);
      }
      const restoredLayer = restoredFeedback.layers[restoredFeedback.activeIndex] ?? null;
      renderStoredLayer(mountedEditor, restoredLayer, restoredFeedback.visible);
      disposeAutosave.current?.();
      disposeAutosave.current = startAutosave(mountedEditor, spaceId, {
        onSave: () => {
          touchSpace(spaceId);
          flashSaved();
        },
      });
    },
    [flashSaved, problem, renderStoredLayer, spaceId],
  );

  return (
    <div className="relative h-full">
      {feedbackHost
        ? createPortal(
            <TutorFeedbackBar
              busy={isThinking}
              error={error}
              layer={feedbackHistory.layers[feedbackHistory.activeIndex] ?? null}
              activeIndex={feedbackHistory.activeIndex}
              layerCount={feedbackHistory.layers.length}
              visible={feedbackHistory.visible}
              warning={feedbackWarning}
              onPrevious={() => handleMoveFeedback(-1)}
              onNext={() => handleMoveFeedback(1)}
              onToggle={handleToggleFeedback}
            />,
            feedbackHost,
          )
        : null}
      {thinkingHost && isThinking
        ? createPortal(<ThinkingPill />, thinkingHost)
        : null}
      <ProblemShapeProvider problem={problem}>
        <Tldraw
          hideUi
          onMount={handleMount}
          options={{ maxPages: 1 }}
          shapeUtils={[ProblemShapeUtil]}
        >
          <CanvasToolbar />
          <SaveIndicator visible={justSaved} />
          <TutorControls
            busyMode={busyMode}
            hasProblem={problem !== undefined}
            hasStudentWork={hasStudentCanvasWork}
            onAnalyze={handleAnalyze}
          />
        </Tldraw>
      </ProblemShapeProvider>
    </div>
  );
}
