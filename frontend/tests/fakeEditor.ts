/**
 * A minimal stand-in for the tldraw Editor.
 *
 * Only the surface our own modules actually call is implemented, and every
 * mutation is recorded so tests can assert on what was asked of the editor
 * rather than on tldraw's internals.
 */

import type { Box, Editor, TLShape, TLShapeId, TLShapePartial } from "tldraw";
import { vi } from "vitest";

export function box(x: number, y: number, w: number, h: number): Box {
  return { x, y, w, h } as Box;
}

export interface FakeShape {
  id: string;
  type: string;
  meta?: Record<string, unknown>;
  props?: Record<string, unknown>;
  pageBounds?: Box | null;
}

export interface FakeEditorOptions {
  shapes?: FakeShape[];
  pageBounds?: Box | null;
  viewport?: Box | null;
  zoom?: number;
  image?: { blob: Blob; width: number; height: number } | null;
}

export interface FakeEditor {
  editor: Editor;
  created: TLShapePartial[];
  deleted: TLShapeId[];
  toImageCalls: { ids: TLShapeId[]; opts: Record<string, unknown> }[];
  shapes: Map<string, FakeShape>;
}

export function makeEditor(options: FakeEditorOptions = {}): FakeEditor {
  const {
    shapes = [],
    pageBounds = box(0, 0, 1000, 800),
    viewport = box(-50, -25, 500, 400),
    zoom = 1.5,
    image = { blob: new Blob(["png"], { type: "image/png" }), width: 800, height: 640 },
  } = options;

  const store = new Map(shapes.map((s) => [s.id, s]));
  const created: TLShapePartial[] = [];
  const deleted: TLShapeId[] = [];
  const toImageCalls: { ids: TLShapeId[]; opts: Record<string, unknown> }[] = [];

  const editor = {
    getCurrentPageShapeIds: () => new Set(store.keys()) as Set<TLShapeId>,
    getCurrentPageBounds: () => pageBounds,
    getViewportPageBounds: () => viewport,
    getZoomLevel: () => zoom,
    getShape: (id: TLShapeId) => store.get(id as string) as unknown as TLShape | undefined,
    getShapePageBounds: (shape: TLShape) =>
      (store.get((shape as unknown as FakeShape).id)?.pageBounds ?? null) as Box,
    toImage: vi.fn(async (ids: TLShapeId[], opts: Record<string, unknown>) => {
      toImageCalls.push({ ids: [...ids], opts });
      return image;
    }),
    createShapes: (partials: TLShapePartial[]) => {
      created.push(...partials);
      for (const p of partials) {
        store.set(p.id as string, {
          id: p.id as string,
          type: p.type as string,
          meta: p.meta as Record<string, unknown>,
        });
      }
    },
    deleteShapes: (ids: TLShapeId[]) => {
      deleted.push(...ids);
      for (const id of ids) store.delete(id as string);
    },
  } as unknown as Editor;

  return { editor, created, deleted, toImageCalls, shapes: store };
}
