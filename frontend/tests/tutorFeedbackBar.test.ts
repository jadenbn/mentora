import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TutorFeedbackBar } from "@/features/tutor/TutorFeedbackBar";
import type { FeedbackLayer } from "@/lib/tutor/feedbackHistory";

const layer: FeedbackLayer = {
  id: "interaction_1",
  mode: "hint",
  createdAt: "2026-01-01T00:00:00Z",
  bounds: { x: 0, y: 0, w: 100, h: 100 },
  snapshot: { document: { shapes: [] } },
  response: {
    interaction_id: "interaction_1",
    status: "partial",
    summary: "Look at the inner function.",
    canvas_actions: [],
  },
};

const render = (over: Partial<Parameters<typeof TutorFeedbackBar>[0]> = {}) =>
  renderToStaticMarkup(
    createElement(TutorFeedbackBar, {
      busy: false,
      error: null,
      layer,
      activeIndex: 0,
      layerCount: 2,
      visible: true,
      warning: null,
      onPrevious: () => undefined,
      onNext: () => undefined,
      onToggle: () => undefined,
      ...over,
    }),
  );

describe("TutorFeedbackBar", () => {
  it("shows navigation, summary, count, and visibility control", () => {
    const html = render();
    expect(html).toContain("Look at the inner function.");
    expect(html).toContain("katex");
    expect(html).toContain("1 / 2");
    expect(html).toContain("Previous tutor feedback");
    expect(html).toContain("Next tutor feedback");
    expect(html).toContain("Hide tutor feedback");
  });

  it("leaves thinking presentation to the canvas pill", () => {
    const html = render({ busy: true, layer: null, layerCount: 0, activeIndex: -1 });
    expect(html).toBe("");
  });

  it("hides the summary and navigation when the layer is hidden", () => {
    const html = render({ visible: false });
    expect(html).toContain("Show tutor feedback");
    expect(html).not.toContain("Look at the inner function.");
    expect(html).not.toContain("1 / 2");
    expect(html).not.toContain("Previous tutor feedback");
    expect(html).not.toContain("Next tutor feedback");
  });
});
