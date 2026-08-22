"use client";

import dynamic from "next/dynamic";
import { useRef } from "react";
import { createShapeId, Editor, toRichText, useEditor } from "tldraw";

const Tldraw = dynamic(() => import("tldraw").then((module) => module.Tldraw), {
  ssr: false,
});

export function Whiteboard() {
  const editor = useRef<Editor>(null);

  const drawThing = () => {
    const id = createShapeId("firs tshape");
    editor.current?.createShape({
      id,
      type: "geo",
      x: 128,
      y: 128,
      props: {
        geo: "rectangle",
        w: 120,
        h: 120,
        dash: "draw",
        color: "black",
        size: "m",
        richText: toRichText("hello!!"),
      },
    });
  };

  return (
    <>
      <button className="mt-10" onClick={drawThing}>
        asdf
      </button>
      <Tldraw
        onMount={(edit) => {
          editor.current = edit;
        }}
      />
    </>
  );
}
