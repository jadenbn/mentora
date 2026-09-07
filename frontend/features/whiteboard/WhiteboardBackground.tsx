import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Editor, useEditor } from "tldraw";
import { VERTICAL_PAGE_ID } from "@/lib/canvas/verticalPage";

type PageScreenFrame = {
  left: number;
  top: number;
  width: number;
  height: number;
  pageHeight: number;
  dotSpacing: number;
};

function getPageScreenFrame(currentEditor: Editor): PageScreenFrame | null {
  const page = currentEditor.getShape(VERTICAL_PAGE_ID);
  if (!page) return null;

  const props = page.props as { w?: unknown; h?: unknown };
  const pageX = Number(page.x);
  const pageY = Number(page.y);
  const pageWidth = Number(props.w);
  const pageHeight = Number(props.h);
  if (
    !Number.isFinite(pageX) ||
    !Number.isFinite(pageY) ||
    !Number.isFinite(pageWidth) ||
    !Number.isFinite(pageHeight) ||
    pageWidth <= 0 ||
    pageHeight <= 0
  ) {
    return null;
  }

  const viewport = currentEditor.getViewportScreenBounds();
  const topLeft = currentEditor.pageToScreen({ x: pageX, y: pageY });
  const bottomRight = currentEditor.pageToScreen({
    x: pageX + pageWidth,
    y: pageY + pageHeight,
  });
  const left = topLeft.x - viewport.x;
  const top = topLeft.y - viewport.y;
  const right = bottomRight.x - viewport.x;
  const bottom = bottomRight.y - viewport.y;
  const dotSpacing = Math.max(
    8,
    currentEditor.getDocumentSettings().gridSize * currentEditor.getZoomLevel(),
  );

  return {
    left,
    top,
    width: right - left,
    height: bottom - top,
    pageHeight,
    dotSpacing,
  };
}

function DocumentBackground() {
  const currentEditor = useEditor();
  const [frame, setFrame] = useState(() => getPageScreenFrame(currentEditor));
  const pageRef = useRef<HTMLDivElement | null>(null);
  const previousFrame = useRef<PageScreenFrame | null>(null);
  const growthAnimation = useRef<Animation | null>(null);

  useEffect(() => {
    const updateFrame = () => {
      const next = getPageScreenFrame(currentEditor);
      setFrame((current) => {
        if (
          current?.left === next?.left &&
          current?.top === next?.top &&
          current?.width === next?.width &&
          current?.height === next?.height &&
          current?.pageHeight === next?.pageHeight &&
          current?.dotSpacing === next?.dotSpacing
        ) {
          return current;
        }
        return next;
      });
    };

    updateFrame();
    const disposeStoreListener = currentEditor.store.listen(updateFrame);

    return () => {
      disposeStoreListener();
    };
  }, [currentEditor]);

  useLayoutEffect(() => {
    const previous = previousFrame.current;
    const pageElement = pageRef.current;
    if (
      previous &&
      frame &&
      pageElement &&
      frame.pageHeight > previous.pageHeight
    ) {
      const currentHeight =
        growthAnimation.current?.playState === "running"
          ? pageElement.getBoundingClientRect().height
          : previous.height;
      growthAnimation.current?.cancel();
      growthAnimation.current = pageElement.animate(
        [
          { height: `${currentHeight}px` },
          { height: `${frame.height}px` },
        ],
        {
          duration: 700,
          easing: "cubic-bezier(0.16, 1, 0.3, 1)",
        },
      );
    }
    previousFrame.current = frame;
  }, [frame]);

  useEffect(() => {
    return () => growthAnimation.current?.cancel();
  }, []);

  return (
    <div className="mentora-canvas-background">
      {frame ? (
        <div
          aria-hidden="true"
          className="mentora-document-page"
          ref={pageRef}
          style={{
            left: frame.left,
            top: frame.top,
            width: frame.width,
            height: frame.height,
            backgroundSize: `${frame.dotSpacing}px ${frame.dotSpacing}px`,
          }}
        />
      ) : null}
    </div>
  );
}

export const WHITEBOARD_COMPONENTS = {
  Background: DocumentBackground,
  Grid: null,
};
