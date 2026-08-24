"use client";

import dynamic from "next/dynamic";
import { ChevronLeft } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
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
import { ProblemCard } from "@/features/problems/ProblemCard";
import { TutorControls } from "@/features/tutor/TutorControls";
import { clearAiShapes } from "@/lib/annotations/renderCanvasActions";
import { loadCanvas, startAutosave } from "@/lib/canvas/persistence";
import { saveCanvas } from "@/lib/canvas/persistence";
import { removeLegacyProblemShape } from "@/lib/problems/renderProblem";
import { touchSpace } from "@/lib/spaces/store";
import { EmptyCanvasError, runTutorAnalysis } from "@/lib/tutor/analyze";
import type { TutorMode, TutorResponse } from "@/types/tutor";
import type { Problem } from "@/types/domain";

const Tldraw = dynamic(() => import("tldraw").then((module) => module.Tldraw), {
  ssr: false,
});

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
      <div className="rounded-xl border border-[#cbd9cf] bg-[#f4f8f4] p-3">
        <p className="mb-1 text-[0.65rem] font-bold uppercase tracking-[0.14em] text-[#607d6c]">
          {response.status}
        </p>
        {response.summary ? (
          <p className="text-sm leading-relaxed text-[#465149]">{response.summary}</p>
        ) : (
          <p className="text-sm text-[#667169]">
            {response.canvas_actions.length} annotation
            {response.canvas_actions.length === 1 ? "" : "s"} added to the board.
          </p>
        )}
      </div>
    </div>
  );
}

function CanvasPanel({
  host,
  onAnalyze,
  onClear,
  busyMode,
  response,
  error,
}: {
  host: HTMLElement | null;
  onAnalyze: (mode: TutorMode) => void;
  onClear: () => void;
  busyMode: TutorMode | null;
  response: TutorResponse | null;
  error: string | null;
}) {
  const [open, setOpen] = useState(false);

  if (!host) {
    return null;
  }

  return createPortal(
    <>
      <button
        aria-controls="canvas-panel"
        aria-expanded={open}
        aria-label={open ? "Close tutor panel" : "Open tutor panel"}
        className={`pointer-events-auto absolute top-1/2 z-40 flex h-14 w-10 -translate-y-1/2 items-center justify-center rounded-l-full border border-r-0 border-[#d9d6cc] bg-[#fffdf8] text-[#354139] shadow-md transition-all duration-300 ease-out min-[1280px]:hidden ${open ? "left-0 -translate-x-full" : "right-0"}`}
        onClick={() => setOpen((isOpen) => !isOpen)}
        type="button"
      >
        <ChevronLeft
          aria-hidden="true"
          className={`size-6 transition-transform duration-300 ease-out ${open ? "rotate-180" : ""}`}
          strokeWidth={2}
        />
      </button>
      <aside
        className={`pointer-events-auto absolute inset-0 z-30 overflow-y-auto border-l border-[#d9d6cc] bg-[#fffdf8] p-5 shadow-2xl transition-transform duration-300 ease-out min-[1280px]:translate-x-0 min-[1280px]:shadow-none ${open ? "translate-x-0" : "translate-x-full"}`}
        id="canvas-panel"
      >
        <section>
          <p className="text-[0.65rem] font-bold uppercase tracking-[0.18em] text-[#607d6c]">
            Tutor
          </p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight text-[#202620]">
            Work through it
          </h2>
          <p className="mt-1 text-sm leading-relaxed text-[#667169]">
            Write naturally, then ask for feedback on what is visible.
          </p>
        </section>

        <section className="mt-5 border-t border-[#e2dfd6] pt-5">
          <div>
            <TutorControls
              busyMode={busyMode}
              onAnalyze={onAnalyze}
              onClear={onClear}
            />
          </div>
          <TutorResult error={error} response={response} />
        </section>

        <section className="mt-6 border-t border-[#e2dfd6] pt-5">
          <h3 className="text-sm font-bold text-[#283129]">Drawing style</h3>
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
      </aside>
    </>,
    host,
  );
}

export function Whiteboard({
  spaceId,
  courseId,
  problem,
}: {
  spaceId: string;
  courseId: string;
  problem?: Problem;
}) {
  const editor = useRef<Editor | null>(null);
  const disposeAutosave = useRef<(() => void) | null>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [drawerHost, setDrawerHost] = useState<HTMLDivElement | null>(null);
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
          courseId,
          problem,
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
    [busyMode, courseId, problem],
  );

  const handleClear = useCallback(() => {
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
      if (problem && removeLegacyProblemShape(mountedEditor, problem.id)) {
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
    <div className="flex h-full min-h-0 flex-col bg-[#f5f2e9]">
      {problem ? <ProblemCard problem={problem} /> : null}
      <div className="relative grid min-h-0 flex-1 grid-cols-1 overflow-hidden min-[1280px]:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="relative min-h-0 min-w-0 border-r border-[#d9d6cc] bg-[#eef0ed]">
          <Tldraw
            hideUi
            onMount={handleMount}
            options={{ maxPages: 1 }}
          >
            <div className="pointer-events-none absolute left-20 top-4 z-20 rounded-full bg-white/80 px-3 py-1 text-[0.65rem] font-bold uppercase tracking-[0.16em] text-[#829087] shadow-sm backdrop-blur">
              Your work
            </div>
            <CanvasToolbar />
            <SaveIndicator visible={justSaved} />
            <CanvasPanel
              busyMode={busyMode}
              error={error}
              host={drawerHost}
              onAnalyze={handleAnalyze}
              onClear={handleClear}
              response={response}
            />
          </Tldraw>
        </div>
        <div
          className="pointer-events-none absolute inset-y-0 right-0 z-50 w-80 min-[1280px]:static min-[1280px]:z-0"
          ref={setDrawerHost}
        />
      </div>
    </div>
  );
}
