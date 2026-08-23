"use client";

import dynamic from "next/dynamic";
import { ChevronLeft } from "lucide-react";
import { useCallback, useRef, useState } from "react";
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
  toRichText,
} from "tldraw";
import { TutorControls } from "@/features/tutor/TutorControls";
import { clearAiShapes } from "@/lib/annotations/renderCanvasActions";
import { EmptyCanvasError, runTutorAnalysis } from "@/lib/tutor/analyze";
import type {
  PriorTutorInteraction,
  ProblemContext,
  TutorMode,
  TutorResponse,
} from "@/types/tutor";

const Tldraw = dynamic(() => import("tldraw").then((module) => module.Tldraw), {
  ssr: false,
});

const DEMO_USER_ID = "user_local";

export interface WhiteboardProblem {
  id: string;
  context: ProblemContext;
}

interface AssistanceCounts {
  hints: number;
  stuck: number;
}

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
  busyMode,
  response,
  error,
}: {
  onAnalyze: (mode: TutorMode) => void;
  onClear: () => void;
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
      </aside>
    </>
  );
}

export function Whiteboard({
  courseId,
  sessionId,
  problem,
}: {
  courseId: string;
  sessionId: string;
  problem: WhiteboardProblem;
}) {
  const editor = useRef<Editor | null>(null);
  const requestInFlight = useRef(false);
  const recentInteractions = useRef<PriorTutorInteraction[]>([]);
  const assistance = useRef<AssistanceCounts>({ hints: 0, stuck: 0 });
  const [busyMode, setBusyMode] = useState<TutorMode | null>(null);
  const [response, setResponse] = useState<TutorResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleAnalyze = useCallback(
    async (mode: TutorMode) => {
      const current = editor.current;
      if (!current || requestInFlight.current) {
        return;
      }

      requestInFlight.current = true;
      setBusyMode(mode);
      setError(null);

      try {
        const result = await runTutorAnalysis({
          editor: current,
          mode,
          userId: DEMO_USER_ID,
          courseId,
          sessionId,
          problemId: problem.id,
          problem: problem.context,
          recentInteractions: recentInteractions.current,
          studentModel: {
            total_hints_used: assistance.current.hints,
          },
        });
        recentInteractions.current = [
          ...recentInteractions.current,
          {
            interaction_id: result.interaction_id,
            mode,
            summary: result.summary ?? `${mode} feedback was added to the canvas.`,
            created_at: new Date().toISOString(),
          },
        ].slice(-20);
        if (mode === "hint") {
          assistance.current.hints += 1;
        } else if (mode === "stuck") {
          assistance.current.stuck += 1;
        }
        setResponse(result);
      } catch (caught) {
        setResponse(null);
        setError(
          caught instanceof EmptyCanvasError || caught instanceof Error
            ? caught.message
            : "The tutor request failed.",
        );
      } finally {
        requestInFlight.current = false;
        setBusyMode(null);
      }
    },
    [courseId, problem, sessionId],
  );

  const handleClear = useCallback(() => {
    if (editor.current) {
      clearAiShapes(editor.current);
    }
    setResponse(null);
    setError(null);
  }, []);

  return (
    <div className="relative h-full">
      <Tldraw
        hideUi
        onMount={(mountedEditor) => {
          editor.current = mountedEditor;
          if (mountedEditor.getCurrentPageShapeIds().size === 0) {
            mountedEditor.createShape({
              type: "text",
              x: 120,
              y: 80,
              meta: { owner: "system", problemId: problem.id },
              props: {
                richText: toRichText(problem.context.prompt_text),
                color: "black",
                size: "l",
              },
            });
          }
        }}
        options={{ maxPages: 1 }}
      >
        <CanvasToolbar />
        <CanvasPanel
          busyMode={busyMode}
          error={error}
          onAnalyze={handleAnalyze}
          onClear={handleClear}
          response={response}
        />
      </Tldraw>
    </div>
  );
}
