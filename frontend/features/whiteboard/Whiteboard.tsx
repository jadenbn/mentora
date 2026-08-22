"use client";

import dynamic from "next/dynamic";
import { useRef } from "react";
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
        onMount={(mountedEditor) => {
          editor.current = mountedEditor;
        }}
      />
      <button
        className="absolute left-1/2 hover:cursor-grab top-4 z-10 rounded bg-blue-700 px-3 py-2 text-sm font-semibold text-white shadow"
        onClick={() =>
          drawTutorAnnotation({ text: "Check this sign", x: 300, y: 200 })
        }
      >
        Add tutor note
      </button>
    </div>
  );
}
