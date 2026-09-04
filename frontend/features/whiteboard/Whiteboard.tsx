"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect } from "react";
import { createPortal } from "react-dom";
import { StatusPill } from "@/features/tutor/StatusPill";
import { TutorControls } from "@/features/tutor/TutorControls";
import { TutorFeedbackBar } from "@/features/tutor/TutorFeedbackBar";
import { VoiceControl } from "@/features/tutor/VoiceControl";
import { SaveIndicator } from "@/features/whiteboard/SaveIndicator";
import { WHITEBOARD_COMPONENTS } from "@/features/whiteboard/WhiteboardBackground";
import { WhiteboardToolbar } from "@/features/whiteboard/WhiteboardToolbar";
import { useWhiteboardSession } from "@/features/whiteboard/useWhiteboardSession";
import { ProblemShapeProvider, ProblemShapeUtil } from "@/lib/problems/ProblemShape";
import { useVoiceCapture } from "@/lib/voice/useVoiceCapture";
import type { ProblemContext } from "@/types/domain";

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
  const { hasStudentCanvasWork, runAnalysis } = session;
  const handleSpokenQuestion = useCallback(
    (transcript: string) =>
      runAnalysis(hasStudentCanvasWork ? "explain" : "stuck", transcript),
    [hasStudentCanvasWork, runAnalysis],
  );
  const voice = useVoiceCapture({ submit: handleSpokenQuestion });
  const cancelVoice = voice.cancel;

  useEffect(() => {
    return () => cancelVoice();
  }, [cancelVoice, spaceId]);

  const viewingHistory =
    session.feedbackHistory.activeIndex >= 0 &&
    session.feedbackHistory.activeIndex < session.feedbackHistory.layers.length - 1;
  const controlsDisabled = viewingHistory || voice.phase.status !== "idle";

  return (
    <div className="relative h-full">
      {feedbackHost
        ? createPortal(
            <TutorFeedbackBar
              busy={session.isThinking}
              error={session.error}
              layer={
                session.feedbackHistory.layers[
                  session.feedbackHistory.activeIndex
                ] ?? null
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
        ? createPortal(<StatusPill label="Thinking" />, thinkingHost)
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
          <VoiceControl
            error={voice.error}
            onAsk={voice.ask}
            onCancel={voice.cancel}
            onEdit={voice.edit}
            onRerecord={voice.rerecord}
            onStop={voice.stop}
            phase={voice.phase}
          />
          <TutorControls
            busyMode={session.busyMode}
            disabled={controlsDisabled}
            hasProblem={problem !== undefined}
            hasStudentWork={session.hasStudentCanvasWork}
            onAnalyze={session.handleAnalyze}
            onStartVoice={voice.start}
          />
        </Tldraw>
      </ProblemShapeProvider>
    </div>
  );
}
