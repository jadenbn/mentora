"use client";

import dynamic from "next/dynamic";
import { useRef, useState } from "react";
import { Editor, toRichText } from "tldraw";

const Tldraw = dynamic(() => import("tldraw").then((module) => module.Tldraw), {
  ssr: false,
});

type TutorAnnotation = {
  // tmp, will add more fields later
  text: string;
  x: number;
  y: number;
};

export function Whiteboard() {
  const editor = useRef<Editor | null>(null);
  const [annotation, setAnnotation] = useState<TutorAnnotation>({
    text: "Check this sign",
    x: 300,
    y: 200,
  });

  const drawTutorAnnotation = (annotation: TutorAnnotation) => {
    editor.current?.createShape({
      type: "text",
      x: annotation.x,
      y: annotation.y,
      meta: { owner: "ai" },
      props: {
        richText: toRichText(annotation.text),
        color: "red",
        size: "m",
      },
    });
  };

  return (
    <div className="relative h-full">
      <Tldraw
        options={{ maxPages: 1 }}
        onMount={(mountedEditor) => {
          editor.current = mountedEditor;
        }}
      />
      <form
        className="absolute left-1/2 top-4 z-10 flex -translate-x-1/2 items-end gap-2 rounded bg-white p-2 shadow"
        onSubmit={(event) => {
          event.preventDefault();
          drawTutorAnnotation(annotation);
        }}
      >
        <label className="grid gap-1 text-xs font-semibold text-slate-700">
          Text
          <input className="w-36 rounded border border-slate-300 px-2 py-1" value={annotation.text} onChange={(event) => setAnnotation({ ...annotation, text: event.target.value })} />
        </label>
        <label className="grid gap-1 text-xs font-semibold text-slate-700">
          X
          <input className="w-16 rounded border border-slate-300 px-2 py-1" type="number" value={annotation.x} onChange={(event) => setAnnotation({ ...annotation, x: Number(event.target.value) })} />
        </label>
        <label className="grid gap-1 text-xs font-semibold text-slate-700">
          Y
          <input className="w-16 rounded border border-slate-300 px-2 py-1" type="number" value={annotation.y} onChange={(event) => setAnnotation({ ...annotation, y: Number(event.target.value) })} />
        </label>
        <button className="hover:cursor-grab rounded bg-blue-700 px-3 py-2 text-sm font-semibold text-white" type="submit">
          Add tutor note
        </button>
      </form>
    </div>
  );
}
