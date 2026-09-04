"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { AskComposer } from "@/features/tutor/AskComposer";
import { StatusPill } from "@/features/tutor/StatusPill";
import { TutorControls } from "@/features/tutor/TutorControls";
import { TutorFeedbackBar } from "@/features/tutor/TutorFeedbackBar";
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
  const [askOpen, setAskOpen] = useState(false);
  const submitQuestion = useCallback(
    (question: string) =>
      runAnalysis(hasStudentCanvasWork ? "explain" : "stuck", question),
    [hasStudentCanvasWork, runAnalysis],
  );
  const handleSpokenQuestion = useCallback(
    async (transcript: string) => {
      await submitQuestion(transcript);
      setAskOpen(false);
    },
    [submitQuestion],
  );
  const voice = useVoiceCapture({ submit: handleSpokenQuestion });
  const cancelVoice = voice.cancel;

  useEffect(() => {
    return () => cancelVoice();
  }, [cancelVoice, spaceId]);

  const viewingHistory =
    session.feedbackHistory.activeIndex >= 0 &&
    session.feedbackHistory.activeIndex < session.feedbackHistory.layers.length - 1;
  const controlsDisabled =
    viewingHistory || voice.phase.status !== "idle" || askOpen;

  const closeAsk = useCallback(() => {
    cancelVoice();
    setAskOpen(false);
  }, [cancelVoice]);

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
          {askOpen ? (
            <AskComposer
              hasSelection={session.hasStudentSelection}
              hasStudentWork={session.hasStudentCanvasWork}
              onAsk={submitQuestion}
              onClose={closeAsk}
              onVoiceAsk={voice.ask}
              onVoiceCancel={voice.cancel}
              onVoiceEdit={voice.edit}
              onVoiceRerecord={voice.rerecord}
              onVoiceStart={voice.start}
              onVoiceStop={voice.stop}
              open
              phase={voice.phase}
              voiceError={voice.error}
            />
          ) : null}
          <TutorControls
            busyMode={session.busyMode}
            disabled={controlsDisabled}
            hasProblem={problem !== undefined}
            hasSelection={session.hasStudentSelection}
            hasStudentWork={session.hasStudentCanvasWork}
            onAnalyze={session.handleAnalyze}
            onOpenAsk={() => setAskOpen(true)}
          />
        </Tldraw>
      </ProblemShapeProvider>
    </div>
  );
}
