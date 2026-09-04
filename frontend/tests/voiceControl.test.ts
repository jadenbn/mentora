/**
 * A spoken question as a student sees it.
 *
 * Two rules under test. No state is communicated by colour alone: every one of
 * them says in words what is happening and what can be done about it. And
 * nothing reaches the tutor without being shown first — the confirmation step
 * has to offer the words, a way to fix them, and all three ways out.
 */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { VoiceControl } from "@/features/tutor/VoiceControl";
import type { VoicePhase } from "@/lib/voice/voiceCapture";

function render(phase: VoicePhase, error: string | null = null): string {
  return renderToStaticMarkup(
    createElement(VoiceControl, {
      phase,
      error,
      onStop: () => undefined,
      onCancel: () => undefined,
      onEdit: () => undefined,
      onAsk: () => undefined,
      onRerecord: () => undefined,
    }),
  );
}

describe("idle", () => {
  it("shows nothing at all, so a quiet board stays quiet", () => {
    // The microphone that starts this lives in the tutor fan now.
    expect(render({ status: "idle" })).toBe("");
  });

  it("still shows a failure the student has not seen yet", () => {
    const html = render({ status: "idle" }, "Microphone access is blocked.");

    expect(html).toContain('role="alert"');
    expect(html).toContain("Microphone access is blocked.");
  });
});

describe("recording", () => {
  const html = () => render({ status: "recording", startedAt: Date.now() });

  it("says it is recording in words, not only in colour", () => {
    expect(html()).toContain("Recording");
  });

  it("announces the state politely rather than interrupting a stroke", () => {
    expect(html()).toContain('role="status"');
  });

  it("offers both stop and cancel", () => {
    expect(html()).toContain('aria-label="Stop recording"');
    expect(html()).toContain('aria-label="Cancel recording"');
  });

  it("starts the elapsed readout at zero rather than a stale clock", () => {
    expect(html()).toContain("0:00");
  });
});

describe("the states between recording and a transcript", () => {
  it("names what it is doing while transcribing", () => {
    const html = render({ status: "transcribing" });

    expect(html).toContain("Transcribing");
    expect(html).toContain(
      'class="pointer-events-none absolute left-1/2 top-4 z-50 -translate-x-1/2"',
    );
  });

  it("stays cancellable while transcribing", () => {
    expect(render({ status: "transcribing" })).toContain('aria-label="Cancel recording"');
  });

  it("names what it is doing while the recorder finishes", () => {
    expect(render({ status: "stopping" })).toContain("Finishing the recording");
  });

  it("does not flash a permission message while starting", () => {
    expect(render({ status: "requesting" })).not.toContain(
      "Waiting for microphone permission",
    );
  });
});

describe("confirming", () => {
  const phase: VoicePhase = { status: "confirming", transcript: "why is this wrong?" };
  const html = () => render(phase);

  it("shows what the tutor heard", () => {
    expect(html()).toContain("why is this wrong?");
  });

  it("offers the transcript in a labelled, editable field", () => {
    expect(html()).toContain("<textarea");
    expect(html()).toContain('for="voice-transcript"');
    expect(html()).toContain('id="voice-transcript"');
  });

  it("offers ask, rerecord, and cancel", () => {
    expect(html()).toContain('aria-label="Ask the tutor this question"');
    expect(html()).toContain('aria-label="Record the question again"');
    expect(html()).toContain('aria-label="Discard this question"');
  });

  it("puts the confirmation controls in a padded bottom-center panel", () => {
    const markup = html();

    expect(markup).toContain("absolute bottom-4 left-1/2");
    expect(markup).toContain("-translate-x-1/2");
    expect(markup).toContain("p-3");
    expect(markup).not.toContain("bg-white/95");
    expect(markup).not.toContain("Edit anything the tutor misheard");
  });

  it("shows no waiting indicator, because nothing is being waited on", () => {
    expect(html()).not.toContain('role="status"');
  });

  it("shows a refused question as an alert without losing the words", () => {
    const refused = render(phase, "There is nothing to ask yet.");

    expect(refused).toContain('role="alert"');
    expect(refused).toContain("why is this wrong?");
  });
});

describe("submitting", () => {
  const html = () =>
    render({ status: "submitting", transcript: "why is this wrong?" });

  it("keeps the question on screen so the student sees what was sent", () => {
    expect(html()).toContain("why is this wrong?");
  });

  it("locks the question rather than letting it be edited mid-flight", () => {
    expect(html()).toMatch(/<textarea[^>]*disabled=""/);
  });

  it("leaves the tutor call to the whiteboard's own indicator", () => {
    // Two live regions for one request would talk over each other.
    expect(html()).not.toContain('role="status"');
  });

  it("offers nothing to cancel, because the request is already gone", () => {
    expect(html()).not.toContain("Cancel");
  });
});
