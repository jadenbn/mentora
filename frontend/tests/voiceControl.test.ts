/**
 * The microphone as a student sees it.
 *
 * The rule under test is that no state is communicated by colour alone: every
 * one of them says in words what is happening and what can be done about it.
 */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { VoiceControl } from "@/features/tutor/VoiceControl";
import type { VoiceStatus } from "@/lib/voice/voiceCapture";

function render(
  status: VoiceStatus,
  over: { error?: string | null; startedAt?: number | null; disabled?: boolean } = {},
): string {
  return renderToStaticMarkup(
    createElement(VoiceControl, {
      status,
      error: over.error ?? null,
      startedAt: over.startedAt ?? null,
      disabled: over.disabled ?? false,
      disabledReason: "Draw on the board first.",
      onStart: () => undefined,
      onStop: () => undefined,
      onCancel: () => undefined,
    }),
  );
}

describe("idle", () => {
  it("offers a labelled microphone button", () => {
    expect(render("idle")).toContain('aria-label="Ask the tutor out loud"');
  });

  it("says why it is unavailable rather than just greying out", () => {
    const html = render("idle", { disabled: true });

    expect(html).toMatch(/disabled=""/);
    expect(html).toContain("Draw on the board first.");
  });

  it("shows nothing to stop or cancel", () => {
    const html = render("idle");

    expect(html).not.toContain("Cancel");
    expect(html).not.toContain(">Stop<");
  });
});

describe("recording", () => {
  const html = () => render("recording", { startedAt: Date.now() });

  it("says it is recording in words, not only in colour", () => {
    expect(html()).toContain("Recording");
  });

  it("announces the state politely rather than interrupting a stroke", () => {
    expect(html()).toContain('role="status"');
  });

  it("offers both stop and cancel", () => {
    expect(html()).toContain('aria-label="Stop recording and ask the tutor"');
    expect(html()).toContain('aria-label="Cancel recording"');
  });

  it("starts the elapsed readout at zero rather than a stale clock", () => {
    expect(html()).toContain("0:00");
  });
});

describe("the states between recording and an answer", () => {
  it("names what it is doing while transcribing", () => {
    expect(render("transcribing")).toContain("Transcribing");
  });

  it("stays cancellable while transcribing", () => {
    expect(render("transcribing")).toContain('aria-label="Cancel recording"');
  });

  it("names what it is doing while the recorder finishes", () => {
    expect(render("stopping")).toContain("Finishing the recording");
  });

  it("explains the permission prompt instead of appearing stuck", () => {
    expect(render("requesting")).toContain("Waiting for microphone permission");
  });

  it("leaves the tutor call to the whiteboard's own indicator", () => {
    // Two live regions for one request would talk over each other.
    const html = render("submitting");

    expect(html).not.toContain('role="status"');
    expect(html).toMatch(/disabled=""/);
  });
});

describe("errors", () => {
  it("shows the message as an alert the student can act on", () => {
    const html = render("idle", { error: "Microphone access is blocked." });

    expect(html).toContain('role="alert"');
    expect(html).toContain("Microphone access is blocked.");
  });

  it("still offers the microphone so the student can try again", () => {
    expect(render("idle", { error: "We did not catch that." })).toContain(
      'aria-label="Ask the tutor out loud"',
    );
  });
});
