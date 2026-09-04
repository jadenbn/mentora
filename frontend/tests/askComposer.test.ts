import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AskComposer } from "@/features/tutor/AskComposer";
import type { VoicePhase } from "@/lib/voice/voiceCapture";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
  .IS_REACT_ACT_ENVIRONMENT = true;

const handlers = () => ({
  onAsk: vi.fn(async () => undefined),
  onClose: vi.fn(),
  onVoiceAsk: vi.fn(),
  onVoiceCancel: vi.fn(),
  onVoiceEdit: vi.fn(),
  onVoiceRerecord: vi.fn(),
  onVoiceStart: vi.fn(),
  onVoiceStop: vi.fn(),
});

function props(over: Partial<Parameters<typeof AskComposer>[0]> = {}) {
  return {
    open: true,
    hasSelection: false,
    hasStudentWork: true,
    phase: { status: "idle" } as VoicePhase,
    voiceError: null,
    ...handlers(),
    ...over,
  };
}

const html = (over: Partial<Parameters<typeof AskComposer>[0]> = {}) =>
  renderToStaticMarkup(createElement(AskComposer, props(over)));

describe("AskComposer context", () => {
  it("stays absent until Ask AI is opened", () => {
    expect(html({ open: false })).toBe("");
  });

  it("explains when the selected work will be used", () => {
    const markup = html({ hasSelection: true });
    expect(markup).toContain("Using selection");
    expect(markup).toContain('aria-label="Ask about your selection"');
  });

  it("distinguishes full work from a problem-only request", () => {
    expect(html()).toContain("Using all work");
    expect(html({ hasStudentWork: false })).toContain("Using problem only");
  });
});

describe("AskComposer voice states", () => {
  it("offers the microphone from the same composer as text", () => {
    const markup = html();
    expect(markup).toContain('aria-label="Ask with microphone"');
    expect(markup).toContain("<textarea");
  });

  it("names recording and offers Stop", () => {
    const markup = html({
      phase: { status: "recording", startedAt: Date.now() },
    });
    expect(markup).toContain("Recording 0:00");
    expect(markup).toContain('aria-label="Stop recording"');
  });

  it("names transcription work in words", () => {
    const markup = html({ phase: { status: "transcribing" } });
    expect(markup).toContain("Transcribing");
    expect(markup).toContain('role="status"');
  });

  it("puts a confirmed transcript into the same visible question field", () => {
    const markup = html({
      phase: { status: "confirming", transcript: "why is this wrong?" },
    });
    expect(markup).toContain('id="ask-ai-question"');
    expect(markup).toContain("why is this wrong?");
    expect(markup).toContain('aria-label="Record the question again"');
    expect(markup).not.toMatch(/<textarea[^>]*disabled=""/);
  });

  it("keeps a failed reviewed transcript visible and editable", () => {
    const markup = html({
      phase: { status: "confirming", transcript: "try this again" },
      voiceError: "The tutor is temporarily unavailable.",
    });
    expect(markup).toContain("try this again");
    expect(markup).toContain('role="alert"');
    expect(markup).toContain("temporarily unavailable");
  });

  it("locks the field while the reviewed transcript is being submitted", () => {
    const markup = html({
      phase: { status: "submitting", transcript: "why?" },
    });
    expect(markup).toMatch(/<textarea[^>]*disabled=""/);
    expect(markup).toContain("Asking…");
  });
});

describe("AskComposer text interaction", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.clearAllMocks();
  });

  async function render(over: Partial<Parameters<typeof AskComposer>[0]> = {}) {
    await act(async () => root.render(createElement(AskComposer, props(over))));
  }

  async function typeQuestion(value: string) {
    const textarea = container.querySelector("textarea") as HTMLTextAreaElement;
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      setValue?.call(textarea, value);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  it("submits trimmed typed text and clears it after success", async () => {
    const onAsk = vi.fn(async () => undefined);
    const onClose = vi.fn();
    await render({ onAsk, onClose });
    await typeQuestion("  focus on this line  ");

    await act(async () => {
      (container.querySelector('button[type="submit"]') as HTMLButtonElement).click();
    });

    expect(onAsk).toHaveBeenCalledWith("focus on this line");
    expect(onClose).toHaveBeenCalledOnce();
    expect((container.querySelector("textarea") as HTMLTextAreaElement).value).toBe("");
  });

  it("preserves typed text for a failed request and permits retry", async () => {
    const onAsk = vi
      .fn<Parameters<typeof AskComposer>[0]["onAsk"]>()
      .mockRejectedValueOnce(new Error("Tutor unavailable"))
      .mockResolvedValueOnce(undefined);
    await render({ onAsk });
    await typeQuestion("Can you explain this?");
    const send = () =>
      container.querySelector('button[type="submit"]') as HTMLButtonElement;

    await act(async () => send().click());
    expect(container.textContent).toContain("Tutor unavailable");
    expect((container.querySelector("textarea") as HTMLTextAreaElement).value).toBe(
      "Can you explain this?",
    );

    await act(async () => send().click());
    expect(onAsk).toHaveBeenCalledTimes(2);
  });

  it("forwards edits to a confirmed transcription", async () => {
    const onVoiceEdit = vi.fn();
    await render({
      phase: { status: "confirming", transcript: "misheard words" },
      onVoiceEdit,
    });
    await typeQuestion("corrected words");
    expect(onVoiceEdit).toHaveBeenCalledWith("corrected words");
  });

  it("routes Close through the teardown callback", async () => {
    const onClose = vi.fn();
    await render({
      phase: { status: "recording", startedAt: Date.now() },
      onClose,
    });
    await act(async () => {
      (container.querySelector(
        'button[aria-label="Close Ask AI"]',
      ) as HTMLButtonElement).click();
    });
    expect(onClose).toHaveBeenCalledOnce();
  });
});
