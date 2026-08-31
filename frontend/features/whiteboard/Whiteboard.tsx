"use client";

import dynamic from "next/dynamic";
import { createPortal } from "react-dom";
import { SaveIndicator } from "@/features/whiteboard/SaveIndicator";
import { TutorControls } from "@/features/tutor/TutorControls";
import { TutorFeedbackBar } from "@/features/tutor/TutorFeedbackBar";
import { ProblemShapeProvider, ProblemShapeUtil } from "@/lib/problems/ProblemShape";
import type { ProblemContext } from "@/types/domain";
import { ThinkingPill } from "@/features/whiteboard/WhiteboardStatus";
import { WhiteboardToolbar } from "@/features/whiteboard/WhiteboardToolbar";
import { WHITEBOARD_COMPONENTS } from "@/features/whiteboard/WhiteboardBackground";
import { useWhiteboardSession } from "@/features/whiteboard/useWhiteboardSession";

const Tldraw = dynamic(() => import("tldraw").then((module) => module.Tldraw), {
  ssr: false,
});

export function Whiteboard({
  spaceId,
  courseId,
  problem,
  feedbackHost,
  thinkingHost,
}: {
  spaceId: string;
  courseId: string;
  problem?: ProblemContext;
  feedbackHost?: HTMLElement | null;
  thinkingHost?: HTMLElement | null;
}) {
  const session = useWhiteboardSession({ spaceId, courseId, problem });

  return (
    <div className="relative h-full">
      {feedbackHost
        ? createPortal(
            <TutorFeedbackBar
              busy={session.isThinking}
              error={session.error}
              layer={
                session.feedbackHistory.layers[session.feedbackHistory.activeIndex] ??
                null
              }
              activeIndex={session.feedbackHistory.activeIndex}
              layerCount={session.feedbackHistory.layers.length}
              visible={session.feedbackHistory.visible}
              warning={session.feedbackWarning}
              onPrevious={() => session.handleMoveFeedback(-1)}
              onNext={() => session.handleMoveFeedback(1)}
              onToggle={session.handleToggleFeedback}
            />,
            feedbackHost,
          )
        : null}
      {thinkingHost && session.isThinking
        ? createPortal(<ThinkingPill />, thinkingHost)
        : null}
      <ProblemShapeProvider problem={problem}>
        <Tldraw
          components={WHITEBOARD_COMPONENTS}
          hideUi
          onMount={session.handleMount}
          options={{ maxPages: 1 }}
          shapeUtils={[ProblemShapeUtil]}
        >
          <WhiteboardToolbar />
          <SaveIndicator visible={session.justSaved} />
          <TutorControls
            busyMode={session.busyMode}
            disabled={
              session.feedbackHistory.activeIndex >= 0 &&
              session.feedbackHistory.activeIndex <
                session.feedbackHistory.layers.length - 1
            }
            hasProblem={problem !== undefined}
            hasStudentWork={session.hasStudentCanvasWork}
            onAnalyze={session.handleAnalyze}
          />
        </Tldraw>
      </ProblemShapeProvider>
    </div>
  );
}
