"use client";

import dynamic from "next/dynamic";
import { Palette as PaletteIcon } from "lucide-react";
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
import { animateCanvasActions } from "@/lib/annotations/animateActions";
import type { AnimationHandle } from "@/lib/annotations/animate";
import {
  clearAiShapes,
  hasAiShapes as getHasAiCanvasFeedback,
} from "@/lib/annotations/renderCanvasActions";
import { hasStudentWork as getHasStudentCanvasWork } from "@/lib/canvas/capture";
import { loadCanvas, startAutosave } from "@/lib/canvas/persistence";
import { saveCanvas } from "@/lib/canvas/persistence";
import { ProblemShapeProvider, ProblemShapeUtil } from "@/lib/problems/ProblemShape";
import { ensureProblemShape } from "@/lib/problems/renderProblem";
import { getStudentId } from "@/lib/student/identity";
import { touchSpace } from "@/lib/spaces/store";
import { EmptyCanvasError, runTutorAnalysis } from "@/lib/tutor/analyze";
import type { ProblemContext } from "@/types/domain";
import type {
  CanvasAction,
  TutorMode,
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

function ThinkingIndicator({ busy, error }: { busy: boolean; error: string | null }) {
  if (busy) {
    return (
      <div
        aria-live="polite"
        className="pointer-events-none absolute left-1/2 top-4 z-50 -translate-x-1/2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm"
        role="status"
      >
        Thinking
        <span aria-hidden="true" className="ml-1 inline-flex gap-0.5">
          <span className="animate-bounce [animation-delay:-0.2s] motion-reduce:animate-none">
            .
          </span>
          <span className="animate-bounce [animation-delay:-0.1s] motion-reduce:animate-none">
            .
          </span>
          <span className="animate-bounce motion-reduce:animate-none">.</span>
        </span>
      </div>
    );
  }

  if (error) {
    return (
      <div
        aria-live="assertive"
        className="pointer-events-none absolute left-1/2 top-4 z-50 -translate-x-1/2 rounded-full border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-800 shadow-sm"
        role="alert"
      >
        {error}
      </div>
    );
  }

  return null;
}

export function Whiteboard({
  spaceId,
  courseId,
  problem,
}: {
  spaceId: string;
  courseId: string;
  problem?: ProblemContext;
}) {
  const editor = useRef<Editor | null>(null);
  const disposeAutosave = useRef<(() => void) | null>(null);
  const disposeWorkListener = useRef<(() => void) | null>(null);
  const animation = useRef<AnimationHandle | null>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [justSaved, setJustSaved] = useState(false);
  const [busyMode, setBusyMode] = useState<TutorMode | null>(null);
  const [isThinking, setIsThinking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasStudentCanvasWork, setHasStudentCanvasWork] = useState(false);
  const [hasAiCanvasFeedback, setHasAiCanvasFeedback] = useState(false);

  const renderTutorActions = useCallback(
    (
      currentEditor: Editor,
      actions: CanvasAction[],
      context: RenderContext,
    ): Promise<void> => {
      animation.current?.cancel();
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
          studentId: getStudentId(),
          sessionId: spaceId,
          renderActions: renderTutorActions,
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
    [busyMode, courseId, problem, spaceId, renderTutorActions],
  );

  const handleClear = useCallback(() => {
    animation.current?.cancel();
    animation.current = null;
    if (editor.current) {
      clearAiShapes(editor.current);
    }
    setHasAiCanvasFeedback(false);
    setIsThinking(false);
    setError(null);
  }, []);

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
      const updateStudentWork = () => {
        const next = getHasStudentCanvasWork(mountedEditor);
        setHasStudentCanvasWork((current) => (current === next ? current : next));
        const hasAiFeedback = getHasAiCanvasFeedback(mountedEditor);
        setHasAiCanvasFeedback((current) =>
          current === hasAiFeedback ? current : hasAiFeedback,
        );
      };
      updateStudentWork();
      disposeWorkListener.current?.();
      disposeWorkListener.current = mountedEditor.store.listen(updateStudentWork);
      if (problem && ensureProblemShape(mountedEditor, problem)) {
        saveCanvas(mountedEditor, spaceId);
      }
      disposeAutosave.current?.();
      disposeAutosave.current = startAutosave(mountedEditor, spaceId, {
        onSave: () => {
          touchSpace(spaceId);
          flashSaved();
        },
      });
    },
    [flashSaved, problem, spaceId],
  );

  return (
    <div className="relative h-full">
      <ProblemShapeProvider problem={problem}>
        <Tldraw
          hideUi
          onMount={handleMount}
          options={{ maxPages: 1 }}
          shapeUtils={[ProblemShapeUtil]}
        >
          <CanvasToolbar />
          <SaveIndicator visible={justSaved} />
          <ThinkingIndicator busy={isThinking} error={error} />
          <TutorControls
            busyMode={busyMode}
            hasFeedback={hasAiCanvasFeedback}
            hasProblem={problem !== undefined}
            hasStudentWork={hasStudentCanvasWork}
            onAnalyze={handleAnalyze}
            onClear={handleClear}
          />
        </Tldraw>
      </ProblemShapeProvider>
    </div>
  );
}
