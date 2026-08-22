"use client";

import dynamic from "next/dynamic";
import { ChevronLeft } from "lucide-react";
import { useRef, useState } from "react";
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

const Tldraw = dynamic(() => import("tldraw").then((module) => module.Tldraw), {
  ssr: false,
});

type TutorAnnotation = {
  text: string;
  x: number;
  y: number;
};

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

function CanvasPanel({
  annotation,
  onAnnotationChange,
  onDrawAnnotation,
}: {
  annotation: TutorAnnotation;
  onAnnotationChange: (annotation: TutorAnnotation) => void;
  onDrawAnnotation: (annotation: TutorAnnotation) => void;
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

        <section className="mt-6">
          <h3 className="text-sm font-semibold text-slate-950">Tutor</h3>
          <div className="mt-2">
            <TutorControls />
          </div>
        </section>

        <form
          className="mt-6 border-t border-slate-200 pt-5"
          onSubmit={(event) => {
            event.preventDefault();
            onDrawAnnotation(annotation);
          }}
        >
          <h3 className="text-sm font-semibold text-slate-950">
            Test tutor annotation
          </h3>
          <label className="mt-3 grid gap-1 text-xs font-semibold text-slate-700">
            Text
            <input
              className="w-full min-w-0 rounded border border-slate-300 px-2 py-1"
              value={annotation.text}
              onChange={(event) =>
                onAnnotationChange({ ...annotation, text: event.target.value })
              }
            />
          </label>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <label className="grid min-w-0 gap-1 text-xs font-semibold text-slate-700">
              X
              <input
                className="w-full min-w-0 rounded border border-slate-300 px-2 py-1"
                type="number"
                value={annotation.x}
                onChange={(event) =>
                  onAnnotationChange({
                    ...annotation,
                    x: Number(event.target.value),
                  })
                }
              />
            </label>
            <label className="grid min-w-0 gap-1 text-xs font-semibold text-slate-700">
              Y
              <input
                className="w-full min-w-0 rounded border border-slate-300 px-2 py-1"
                type="number"
                value={annotation.y}
                onChange={(event) =>
                  onAnnotationChange({
                    ...annotation,
                    y: Number(event.target.value),
                  })
                }
              />
            </label>
          </div>
          <button
            className="mt-3 hover:cursor-grab rounded bg-blue-700 px-3 py-2 text-sm font-semibold text-white"
            type="submit"
          >
            Add tutor note
          </button>
        </form>
      </aside>
    </>
  );
}

export function Whiteboard() {
  const editor = useRef<Editor | null>(null);
  const [annotation, setAnnotation] = useState<TutorAnnotation>({
    text: "Check this sign",
    x: 300,
    y: 200,
  });

  function drawTutorAnnotation(nextAnnotation: TutorAnnotation) {
    editor.current?.createShape({
      type: "text",
      x: nextAnnotation.x,
      y: nextAnnotation.y,
      meta: { owner: "ai" },
      props: {
        richText: toRichText(nextAnnotation.text),
        color: "red",
        size: "m",
      },
    });
  }

  return (
    <div className="relative h-full">
      <Tldraw
        hideUi
        onMount={(mountedEditor) => {
          editor.current = mountedEditor;
        }}
        options={{ maxPages: 1 }}
      >
        <CanvasToolbar />
        <CanvasPanel
          annotation={annotation}
          onAnnotationChange={setAnnotation}
          onDrawAnnotation={drawTutorAnnotation}
        />
      </Tldraw>
    </div>
  );
}
