import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TutorControls } from "@/features/tutor/TutorControls";

function renderControls(
  hasStudentWork: boolean,
  hasProblem: boolean,
  hasFeedback = false,
): string {
  return renderToStaticMarkup(
    createElement(TutorControls, {
      busyMode: null,
      hasProblem,
      hasFeedback,
      hasStudentWork,
      onAnalyze: () => undefined,
      onClear: () => undefined,
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

  it("only shows clear feedback when tutor marks exist", () => {
    expect(renderControls(true, true)).not.toContain(">Clear<");
    expect(renderControls(true, true, true)).toContain(">Clear<");
  });
});
