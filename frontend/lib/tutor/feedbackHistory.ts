import type { TutorMode, TutorResponse } from "@/types/tutor";
import type { WorldBounds } from "@/lib/annotations/geometry";

export const MAX_FEEDBACK_LAYERS = 10;
const VERSION = 1;
const KEY_PREFIX = "mentora:feedback:";

export interface FeedbackLayer {
  id: string;
  mode: TutorMode;
  createdAt: string;
  bounds: WorldBounds;
  response: TutorResponse;
}

export interface FeedbackHistory {
  version: typeof VERSION;
  layers: FeedbackLayer[];
  activeIndex: number;
  visible: boolean;
}

export function emptyFeedbackHistory(): FeedbackHistory {
  return { version: VERSION, layers: [], activeIndex: -1, visible: true };
}

export function feedbackStorageKey(spaceId: string): string {
  return `${KEY_PREFIX}${spaceId}`;
}

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isLayer(value: unknown): value is FeedbackLayer {
  if (!isRecord(value) || !isRecord(value.response) || !isRecord(value.bounds)) {
    return false;
  }
  const response = value.response;
  const bounds = value.bounds;
  return (
    typeof value.id === "string" &&
    ["mark", "hint", "explain", "stuck"].includes(String(value.mode)) &&
    typeof value.createdAt === "string" &&
    typeof bounds.x === "number" &&
    typeof bounds.y === "number" &&
    typeof bounds.w === "number" &&
    typeof bounds.h === "number" &&
    typeof response.interaction_id === "string" &&
    typeof response.status === "string" &&
    Array.isArray(response.canvas_actions) &&
    typeof response.summary === "string"
  );
}

function normalize(value: unknown): FeedbackHistory {
  if (!isRecord(value) || value.version !== VERSION || !Array.isArray(value.layers)) {
    return emptyFeedbackHistory();
  }
  const layers = value.layers.filter(isLayer).slice(-MAX_FEEDBACK_LAYERS);
  const rawIndex = typeof value.activeIndex === "number" ? value.activeIndex : -1;
  const activeIndex = layers.length === 0 ? -1 : Math.min(Math.max(rawIndex, 0), layers.length - 1);
  return {
    version: VERSION,
    layers,
    activeIndex,
    visible: value.visible !== false,
  };
}

export function loadFeedbackHistory(spaceId: string): FeedbackHistory {
  const store = storage();
  if (!store) return emptyFeedbackHistory();
  try {
    return normalize(JSON.parse(store.getItem(feedbackStorageKey(spaceId)) ?? "null"));
  } catch {
    return emptyFeedbackHistory();
  }
}

export function saveFeedbackHistory(spaceId: string, history: FeedbackHistory): boolean {
  const store = storage();
  if (!store) return false;
  try {
    store.setItem(feedbackStorageKey(spaceId), JSON.stringify(history));
    return true;
  } catch {
    return false;
  }
}

export function clearFeedbackHistory(spaceId: string): void {
  try {
    storage()?.removeItem(feedbackStorageKey(spaceId));
  } catch {
    // Storage failure should not interrupt the canvas.
  }
}

export function appendFeedbackLayer(
  history: FeedbackHistory,
  layer: FeedbackLayer,
): { history: FeedbackHistory; dropped: boolean } {
  const all = [...history.layers, layer];
  const dropped = all.length > MAX_FEEDBACK_LAYERS;
  const layers = all.slice(-MAX_FEEDBACK_LAYERS);
  return {
    history: {
      version: VERSION,
      layers,
      activeIndex: layers.length - 1,
      visible: true,
    },
    dropped,
  };
}

export function moveFeedbackLayer(
  history: FeedbackHistory,
  delta: -1 | 1,
): FeedbackHistory {
  if (history.layers.length === 0 || history.activeIndex < 0) return history;
  const activeIndex = Math.min(
    Math.max(history.activeIndex + delta, 0),
    history.layers.length - 1,
  );
  return activeIndex === history.activeIndex
    ? history
    : { ...history, activeIndex, visible: true };
}

export function toggleFeedback(history: FeedbackHistory): FeedbackHistory {
  return history.layers.length === 0
    ? history
    : { ...history, visible: !history.visible };
}
