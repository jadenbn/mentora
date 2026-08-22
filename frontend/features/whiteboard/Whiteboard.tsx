"use client";

import dynamic from "next/dynamic";
import { useRef, useState } from "react";
import { createShapeId, EASINGS, Editor, toRichText, useEditor } from "tldraw";

const Tldraw = dynamic(() => import("tldraw").then((module) => module.Tldraw), {
  ssr: false,
});

export function Whiteboard() {
  const editor = useRef<Editor>(null);
  const [value, setValue] = useState<number>(1);

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

    editor.current?.animateShape({
      id,
      type: "geo",
      opacity: 0,
    }, {
      animation: { duration: 2000, easing: EASINGS.linear },
    });

    setTimeout(() => {
      editor.current?.deleteShape(id);
    }, 2000);
  };

  return (
    <>
      <button className="hover:cursor-grab mt-10 border-2" onClick={drawThing}>
        draw thing
      </button>
      <Tldraw
        onMount={(edit) => {
          editor.current = edit;
        }}
      />
    </>
  );
}
