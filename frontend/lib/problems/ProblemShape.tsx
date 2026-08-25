import { createContext, useContext, useEffect, type ReactNode } from "react";
import {
  BaseBoxShapeUtil,
  HTMLContainer,
  Rectangle2d,
  T,
  useEditor,
} from "@tldraw/editor";
import type { RecordProps, TLShape } from "@tldraw/editor";
import { ProblemBody } from "@/features/problems/ProblemCard";
import { PROBLEM_SHAPE_TYPE } from "@/lib/problems/renderProblem";
import type { ProblemContext } from "@/types/domain";

declare module "@tldraw/tlschema" {
  interface TLGlobalShapePropsMap {
    "mentora-problem": { problemId: string; w: number; h: number };
  }
}

export type ProblemShape = TLShape<typeof PROBLEM_SHAPE_TYPE>;

const ProblemContextForShape = createContext<ProblemContext | null>(null);

export function ProblemShapeProvider({
  problem,
  children,
}: {
  problem?: ProblemContext;
  children: ReactNode;
}) {
  return (
    <ProblemContextForShape.Provider value={problem ?? null}>
      {children}
    </ProblemContextForShape.Provider>
  );
}

function ProblemShapeContent({ shape }: { shape: ProblemShape }) {
  const editor = useEditor();
  const problem = useContext(ProblemContextForShape);

  useEffect(() => {
    if (!problem || problem.id !== shape.props.problemId || typeof ResizeObserver === "undefined") {
      return;
    }
    const element = document.querySelector(`[data-problem-shape="${shape.id}"]`);
    if (!(element instanceof HTMLElement)) return;
    const observer = new ResizeObserver(([entry]) => {
      const nextHeight = Math.max(160, Math.ceil(entry.contentRect.height));
      if (Math.abs(nextHeight - shape.props.h) > 1) {
        editor.updateShape({ id: shape.id, type: PROBLEM_SHAPE_TYPE, props: { h: nextHeight } });
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [editor, problem, shape]);

  return (
    <HTMLContainer
      className="pointer-events-none overflow-hidden rounded-xl border border-slate-300 bg-white p-5 shadow-sm"
      data-problem-shape={shape.id}
      style={{ width: shape.props.w, minHeight: shape.props.h }}
    >
      {problem?.id === shape.props.problemId ? (
        <ProblemBody prompt={problem.prompt} />
      ) : (
        <p className="text-sm text-slate-500">Problem unavailable.</p>
      )}
    </HTMLContainer>
  );
}

export class ProblemShapeUtil extends BaseBoxShapeUtil<ProblemShape> {
  static override type = PROBLEM_SHAPE_TYPE;
  static override props: RecordProps<ProblemShape> = {
    problemId: T.string,
    w: T.number,
    h: T.number,
  };

  override canResize() {
    return false;
  }

  override canBind() {
    return false;
  }

  override getDefaultProps(): ProblemShape["props"] {
    return { problemId: "", w: 680, h: 180 };
  }

  override getGeometry(shape: ProblemShape) {
    return new Rectangle2d({ width: shape.props.w, height: shape.props.h, isFilled: true });
  }

  override component(shape: ProblemShape) {
    return <ProblemShapeContent shape={shape} />;
  }

  override getIndicatorPath(shape: ProblemShape): Path2D {
    const path = new Path2D();
    path.rect(0, 0, shape.props.w, shape.props.h);
    return path;
  }
}
