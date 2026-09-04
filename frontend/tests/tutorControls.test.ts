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
      onOpenAsk: () => undefined,
    }),
  );
}

describe("TutorControls", () => {
  it("enables every action when a structured problem exists", () => {
    const html = renderControls(false, true);

    expect(html).not.toMatch(/disabled=""[^>]*>Mark<\/button>/);
    expect(html).not.toMatch(/disabled=""[^>]*>Hint<\/button>/);
    expect(html).not.toMatch(/disabled=""[^>]*>Explain<\/button>/);
    expect(html).toMatch(/>I’m Stuck<\/button>/);
    expect(html).toMatch(/bg-blue-600[^>]*>I’m Stuck<\/button>/);
  });

  it("disables every action when there is neither work nor a problem", () => {
    const html = renderControls(false, false);

    expect(html).toMatch(/disabled=""[^>]*>Mark<\/button>/);
    expect(html).toMatch(/disabled=""[^>]*>Hint<\/button>/);
    expect(html).toMatch(/disabled=""[^>]*>Explain<\/button>/);
    expect(html).toMatch(/disabled=""[^>]*>I’m Stuck<\/button>/);
    expect(askButton(html)).toContain('disabled=""');
  });

  it("enables all tutor actions once student work exists", () => {
    const html = renderControls(true, true);

    expect(html).not.toMatch(/disabled=""[^>]*>Mark<\/button>/);
    expect(html).not.toMatch(/disabled=""[^>]*>Hint<\/button>/);
    expect(html).not.toMatch(/disabled=""[^>]*>Explain<\/button>/);
    expect(html).not.toMatch(/disabled=""[^>]*>I’m Stuck<\/button>/);
    expect(html).not.toContain("bg-blue-600");
  });
  it("offers one labelled Ask AI action alongside the four modes", () => {
    expect(askButton(renderControls(true, true))).not.toBe("");
    expect(renderControls(true, true)).toContain("Ask AI</button>");
  });

  it("enables Ask AI once there is work or a problem to talk about", () => {
    expect(askButton(renderControls(true, false))).not.toContain('disabled=""');
    expect(askButton(renderControls(false, true))).not.toContain('disabled=""');
  });

  it("says why Ask AI is unavailable rather than just greying out", () => {
    const ask = askButton(renderControls(false, false));

    expect(ask).toContain('disabled=""');
    expect(ask).toContain("before asking AI");
  });
});

/** Ask AI's opening tag, so attribute order cannot fake an assertion. */
function askButton(html: string): string {
  const start = html.indexOf('<button aria-label="Ask AI"');
  return start === -1 ? "" : html.slice(start, html.indexOf(">", start) + 1);
}
