"use client";

import dynamic from "next/dynamic";
import { ChevronLeft } from "lucide-react";
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
} from "tldraw";
import { SaveIndicator } from "@/features/whiteboard/SaveIndicator";
import { TutorControls } from "@/features/tutor/TutorControls";
import { animateCanvasActions } from "@/lib/annotations/animateActions";
import { randomDemoActions } from "@/lib/annotations/demoAnnotation";
import type { AnimationHandle } from "@/lib/annotations/animate";
import { clearAiShapes } from "@/lib/annotations/renderCanvasActions";
import { loadCanvas, startAutosave } from "@/lib/canvas/persistence";
import { touchSpace } from "@/lib/spaces/store";
import { EmptyCanvasError, runTutorAnalysis } from "@/lib/tutor/analyze";
import type { TutorMode, TutorResponse } from "@/types/tutor";

const Tldraw = dynamic(() => import("tldraw").then((module) => module.Tldraw), {
  ssr: false,
});

// TODO: user and problem still come from nowhere. The backend requires both,
// and prompt_text must be non-empty. The course id is real now: it comes from
// the space this canvas belongs to.
const PLACEHOLDER_USER_ID = "user_local";
const PLACEHOLDER_PROBLEM_ID = "problem_demo";
const PLACEHOLDER_PROBLEM_TEXT = "Work shown on the whiteboard.";

function CanvasToolbar() {
  return (
    <TldrawUiToolbar
      className="absolute! left-4! top-1/2! z-20! -translate-y-1/2!"
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
      </TldrawUiMenuContextProvider>
    </TldrawUiToolbar>
  );
}

function TutorResult({
  response,
  error,
}: {
  response: TutorResponse | null;
  error: string | null;
}) {
  if (error) {
    return (
      <p className="mt-3 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
        {error}
      </p>
    );
  }

  if (!response) {
    return null;
  }

  return (
    <div className="mt-3 space-y-2 text-xs text-slate-700">
      <p>
        <span className="font-semibold capitalize text-slate-950">
          {response.status}
        </span>{" "}
        · {Math.round(response.confidence * 100)}% confident ·{" "}
        {response.canvas_actions.length} annotation
        {response.canvas_actions.length === 1 ? "" : "s"}
      </p>

      {response.summary ? <p>{response.summary}</p> : null}

      {response.course_boundary.requires_confirmation ? (
        <p className="rounded border border-amber-200 bg-amber-50 p-2 text-amber-900">
          {response.course_boundary.message ??
            "This may go beyond what the course has covered."}
        </p>
      ) : null}

      {response.warnings.length > 0 ? (
        <ul className="list-disc pl-4 text-amber-800">
          {response.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}

      {response.grounding_references.length > 0 ? (
        <p className="text-slate-500">
          Sources:{" "}
          {response.grounding_references
            .map((reference) => `${reference.filename} p.${reference.page}`)
            .join(", ")}
        </p>
      ) : null}
    </div>
  );
}

function CanvasPanel({
  onAnalyze,
  onClear,
  onAnimateDemo,
  busyMode,
  response,
  error,
}: {
  onAnalyze: (mode: TutorMode) => void;
  onClear: () => void;
  onAnimateDemo: () => void;
  busyMode: TutorMode | null;
  response: TutorResponse | null;
  error: string | null;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        aria-controls="canvas-panel"
        aria-expanded={open}
        aria-label={open ? "Close draw options" : "Open draw options"}
        className={`absolute top-1/2 z-40 flex h-14 w-10 -translate-y-1/2 items-center justify-center rounded-l-full border border-r-0 border-slate-200 bg-white text-slate-950 shadow-md transition-[right] duration-300 ease-out hover:cursor-grab ${open ? "right-72" : "right-0"}`}
        onClick={() => setOpen((isOpen) => !isOpen)}
      >
        <ChevronLeft
          aria-hidden="true"
          className={`size-6 transition-transform duration-300 ease-out ${open ? "rotate-180" : ""}`}
          strokeWidth={2}
        />
      </button>
      <aside
        className={`absolute inset-y-0 right-0 z-30 w-72 overflow-y-auto bg-white p-5 shadow-2xl transition-transform duration-300 ease-out ${open ? "translate-x-0" : "translate-x-full"}`}
        id="canvas-panel"
      >
        <section>
          <h3 className="text-sm font-semibold text-slate-950">Palette</h3>
          <div className="sidebar-style-panel mt-2">
            <DefaultStylePanel isMobile>
              <StylePanelSection>
                <StylePanelColorPicker />
                <StylePanelOpacityPicker />
              </StylePanelSection>
              <StylePanelSection>
                <StylePanelFillPicker />
                <StylePanelDashPicker />
                <StylePanelSizePicker />
              </StylePanelSection>
            </DefaultStylePanel>
          </div>
        </section>

        <section className="mt-6 border-t border-slate-200 pt-5">
          <h3 className="text-sm font-semibold text-slate-950">Tutor</h3>
          <div className="mt-2">
            <TutorControls
              busyMode={busyMode}
              onAnalyze={onAnalyze}
              onClear={onClear}
            />
          </div>
          <TutorResult error={error} response={response} />
        </section>

        <section className="mt-6 border-t border-slate-200 pt-5">
          <h3 className="text-sm font-semibold text-slate-950">Testing</h3>
          <button
            className="mt-2 w-full rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm font-semibold text-slate-900 hover:bg-slate-50"
            onClick={onAnimateDemo}
            type="button"
          >
            Animate test note
          </button>
        </section>
      </aside>
    </>
  );
}

export function Whiteboard({
  spaceId,
  courseId,
}: {
  spaceId: string;
  courseId: string;
}) {
  const editor = useRef<Editor | null>(null);
  const disposeAutosave = useRef<(() => void) | null>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const animation = useRef<AnimationHandle | null>(null);
  const [justSaved, setJustSaved] = useState(false);
  const [busyMode, setBusyMode] = useState<TutorMode | null>(null);
  const [response, setResponse] = useState<TutorResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleAnalyze = useCallback(
    async (mode: TutorMode) => {
      const current = editor.current;
      if (!current || busyMode !== null) {
        return;
      }

      setBusyMode(mode);
      setError(null);

      try {
        const result = await runTutorAnalysis({
          editor: current,
          mode,
          userId: PLACEHOLDER_USER_ID,
          courseId,
          // The wire contract still calls a space's id the session id.
          sessionId: spaceId,
          problemId: PLACEHOLDER_PROBLEM_ID,
          problemText: PLACEHOLDER_PROBLEM_TEXT,
        });
        setResponse(result);
      } catch (caught) {
        setResponse(null);
        setError(
          caught instanceof EmptyCanvasError || caught instanceof Error
            ? caught.message
            : "The tutor request failed.",
        );
      } finally {
        setBusyMode(null);
      }
    },
    [busyMode, courseId, spaceId],
  );

  /** Testing only: draw a random tutor-shaped annotation with animation. */
  const handleAnimateDemo = useCallback(() => {
    const current = editor.current;
    if (!current) {
      return;
    }
    // A second press interrupts the first rather than overlapping it.
    animation.current?.cancel();
    animation.current = animateCanvasActions(current, randomDemoActions(), {
      bounds: current.getViewportPageBounds(),
      interactionId: `demo_${Date.now()}`,
    });
  }, []);

  const handleClear = useCallback(() => {
    animation.current?.cancel();
    animation.current = null;
    if (editor.current) {
      clearAiShapes(editor.current);
    }
    setResponse(null);
    setError(null);
  }, []);

  // Autosave outlives any single render, so tear it down when the space closes.
  useEffect(() => {
    return () => {
      disposeAutosave.current?.();
      disposeAutosave.current = null;
      animation.current?.cancel();
      animation.current = null;
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
      // Restore before the student can draw, so their work is never briefly
      // absent and then overwritten by an autosave of an empty canvas.
      loadCanvas(mountedEditor, spaceId);
      disposeAutosave.current?.();
      disposeAutosave.current = startAutosave(mountedEditor, spaceId, {
        onSave: () => {
          touchSpace(spaceId);
          flashSaved();
        },
      });
    },
    [flashSaved, spaceId],
  );

  return (
    <div className="relative h-full">
      <Tldraw
        hideUi
        onMount={handleMount}
        options={{ maxPages: 1 }}
      >
        <CanvasToolbar />
        <SaveIndicator visible={justSaved} />
        <CanvasPanel
          busyMode={busyMode}
          error={error}
          onAnalyze={handleAnalyze}
          onAnimateDemo={handleAnimateDemo}
          onClear={handleClear}
          response={response}
        />
      </Tldraw>
    </div>
  );
}
