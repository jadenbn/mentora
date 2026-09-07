import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TutorControls } from "@/features/tutor/TutorControls";

function renderControls(
  hasStudentWork: boolean,
  hasProblem: boolean,
): string {
  return renderToStaticMarkup(
    createElement(TutorControls, {
      busyMode: null,
      hasProblem,
      hasStudentWork,
      onAnalyze: () => undefined,
      onStartVoice: () => undefined,
    }),
  );
}

describe("TutorControls", () => {
  it("disables canvas-dependent actions before student work exists", () => {
    const html = renderControls(false, true);

    expect(html).toMatch(/disabled=""[^>]*>Mark<\/button>/);
    expect(html).toMatch(/disabled=""[^>]*>Hint<\/button>/);
    expect(html).toMatch(/disabled=""[^>]*>Explain<\/button>/);
    expect(html).toMatch(/>I’m Stuck<\/button>/);
    expect(html).toMatch(/bg-blue-600[^>]*>I’m Stuck<\/button>/);
  });

  it("also disables I’m Stuck when there is no problem context", () => {
    const html = renderControls(false, false);

    expect(html).toMatch(/disabled=""[^>]*>I’m Stuck<\/button>/);
  });

  it("enables all tutor actions once student work exists", () => {
    const html = renderControls(true, true);

    expect(html).not.toMatch(/disabled=""[^>]*>Mark<\/button>/);
    expect(html).not.toMatch(/disabled=""[^>]*>Hint<\/button>/);
    expect(html).not.toMatch(/disabled=""[^>]*>Explain<\/button>/);
    expect(html).not.toMatch(/disabled=""[^>]*>I’m Stuck<\/button>/);
    expect(html).not.toContain("bg-blue-600");
  });
  it("offers the microphone alongside the tutor actions", () => {
    // Asking out loud is another way to start a tutor request, so it fans out
    // of the same chevron rather than sitting in its own corner.
    expect(micButton(renderControls(true, true))).not.toBe("");
  });

  it("enables the microphone once there is work or a problem to talk about", () => {
    expect(micButton(renderControls(true, false))).not.toContain('disabled=""');
    expect(micButton(renderControls(false, true))).not.toContain('disabled=""');
  });

  it("says why the microphone is unavailable rather than just greying out", () => {
    const mic = micButton(renderControls(false, false));

    expect(mic).toContain('disabled=""');
    expect(mic).toContain("before asking out loud");
  });
});

/** The microphone's opening tag, so attribute order cannot fake an assertion. */
function micButton(html: string): string {
  const start = html.indexOf('<button aria-label="Ask the tutor out loud"');
  return start === -1 ? "" : html.slice(start, html.indexOf(">", start) + 1);
}
