/**
 * The one way the tutor says it is busy.
 *
 * Thinking and Transcribing are the same kind of wait, so they have to be the
 * same object rather than two indicators that merely look alike. The last test
 * here is the one that actually pins that: it renders the pill on its own and
 * finds it, unchanged, inside the voice control.
 */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { StatusPill } from "@/features/tutor/StatusPill";
import { VoiceControl } from "@/features/tutor/VoiceControl";

const pill = (props: Parameters<typeof StatusPill>[0]) =>
  renderToStaticMarkup(createElement(StatusPill, props));

describe("StatusPill", () => {
  it("announces politely rather than interrupting a stroke", () => {
    const html = pill({ label: "Thinking" });

    expect(html).toContain('role="status"');
    expect(html).toContain('aria-live="polite"');
  });

  it("says what it is waiting on in words", () => {
    expect(pill({ label: "Transcribing" })).toContain("Transcribing");
  });

  it("animates the wait, and hides that from assistive tech", () => {
    const html = pill({ label: "Thinking" });

    expect(html).toContain("animate-bounce");
    expect(html).toContain('aria-hidden="true"');
  });

  it("stands still for a reader who asked for no motion", () => {
    expect(pill({ label: "Thinking" })).toContain("motion-reduce:animate-none");
  });

  it("drops the animation for a wait that is not a request", () => {
    // Recording is not something the student is waiting on us for.
    expect(pill({ label: "Recording 0:04", animated: false })).not.toContain(
      "animate-bounce",
    );
  });

  it("carries a state marker that colour alone could not", () => {
    const html = pill({
      label: "Recording 0:04",
      animated: false,
      leading: createElement("span", { className: "recording-dot" }),
    });

    expect(html).toContain("recording-dot");
  });
});

describe("sharing it with the tutor's thinking status", () => {
  it("transcribing renders the very same pill", () => {
    const html = renderToStaticMarkup(
      createElement(VoiceControl, {
        phase: { status: "transcribing" },
        error: null,
        onStop: () => undefined,
        onCancel: () => undefined,
        onEdit: () => undefined,
        onAsk: () => undefined,
        onRerecord: () => undefined,
      }),
    );

    expect(html).toContain(pill({ label: "Transcribing" }));
  });
});
