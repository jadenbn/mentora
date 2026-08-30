import { describe, expect, it } from "vitest";
import {
  MAX_FEEDBACK_LAYERS,
  appendFeedbackLayer,
  emptyFeedbackHistory,
  loadFeedbackHistory,
  moveFeedbackLayer,
  saveFeedbackHistory,
  toggleFeedback,
} from "@/lib/tutor/feedbackHistory";
import type { FeedbackLayer } from "@/lib/tutor/feedbackHistory";

const layer = (id: string): FeedbackLayer => ({
  id,
  mode: "hint",
  createdAt: id,
  bounds: { x: 10, y: 20, w: 300, h: 400 },
  snapshot: { document: { shapes: [id] } },
  response: {
    interaction_id: id,
    status: "partial",
    summary: `Hint ${id}`,
    canvas_actions: [],
  },
});

describe("feedback history", () => {
  it("starts with no active layer", () => {
    expect(emptyFeedbackHistory()).toMatchObject({ layers: [], activeIndex: -1, visible: true });
  });

  it("appends and selects the newest layer", () => {
    const first = appendFeedbackLayer(emptyFeedbackHistory(), layer("one")).history;
    const next = appendFeedbackLayer(first, layer("two")).history;
    expect(next.layers.map((item) => item.id)).toEqual(["one", "two"]);
    expect(next.activeIndex).toBe(1);
    expect(next.visible).toBe(true);
  });

  it("keeps only the newest ten layers and reports the drop", () => {
    let history = emptyFeedbackHistory();
    for (let i = 0; i < MAX_FEEDBACK_LAYERS; i++) {
      history = appendFeedbackLayer(history, layer(String(i))).history;
    }
    const result = appendFeedbackLayer(history, layer("new"));
    expect(result.dropped).toBe(true);
    expect(result.history.layers).toHaveLength(MAX_FEEDBACK_LAYERS);
    expect(result.history.layers[0].id).toBe("1");
    expect(result.history.layers.at(-1)?.id).toBe("new");
  });

  it("moves immediately and reveals the selected historical layer", () => {
    let history = emptyFeedbackHistory();
    history = appendFeedbackLayer(history, layer("one")).history;
    history = appendFeedbackLayer(history, layer("two")).history;
    history = toggleFeedback(history);
    const previous = moveFeedbackLayer(history, -1);
    expect(previous.activeIndex).toBe(0);
    expect(previous.visible).toBe(true);
    expect(moveFeedbackLayer(previous, -1)).toBe(previous);
  });

  it("toggles only the current layer visibility", () => {
    let history = appendFeedbackLayer(emptyFeedbackHistory(), layer("one")).history;
    history = toggleFeedback(history);
    expect(history.visible).toBe(false);
    expect(history.layers).toHaveLength(1);
  });

  it.skipIf(typeof localStorage === "undefined")("round-trips a versioned history per space", () => {
    const history = appendFeedbackLayer(emptyFeedbackHistory(), layer("one")).history;
    expect(saveFeedbackHistory("space_a", history)).toBe(true);
    expect(loadFeedbackHistory("space_a")).toEqual(history);
    expect(loadFeedbackHistory("space_b")).toEqual(emptyFeedbackHistory());
  });

  it.skipIf(typeof localStorage === "undefined")("ignores malformed stored data", () => {
    localStorage.setItem("mentora:feedback:bad", JSON.stringify({ version: 99, layers: [] }));
    expect(loadFeedbackHistory("bad")).toEqual(emptyFeedbackHistory());
  });
});
