# Frontend test suite

Vitest, jsdom environment. Real tldraw is imported rather than mocked; the
browser APIs it needs at import time are polyfilled in `setup.ts`.

```bash
bun run test         # once
bun run test:watch   # watch mode
```

## Layout

| File | Covers |
| --- | --- |
| `fakeEditor.ts` | stand-in for the tldraw `Editor`, recording every mutation |
| `capture.test.ts` | `lib/canvas/capture.ts` — normalization, export bounds, shape context |
| `renderCanvasActions.test.ts` | `lib/annotations/renderCanvasActions.ts` — all eight action types, coordinate conversion, provenance |
| `api.test.ts` | `lib/api/api.ts` — multipart construction, error mapping |
| `analyze.test.ts` | `lib/tutor/analyze.ts` — capture → request → render, with only the network mocked |
| `persistence.test.ts` | **specification only — currently failing on purpose.** See below. |

## The coordinate invariant

Most of the value here is on one seam. The backend answers in coordinates
normalized to the submitted image; the renderer is the only place that converts
them back to tldraw world space. `capture.test.ts` and
`renderCanvasActions.test.ts` pin both directions against a frame whose origin
is deliberately not `(0,0)`, so an implementation that forgets the offset fails
rather than coincidentally passing.

## persistence.test.ts is a specification

Those 31 tests fail against the stub in `lib/canvas/persistence.ts`, which
throws. Each failure names one behaviour still to build:

- a namespaced, per-session localStorage key
- a versioned envelope, so a future format change is detected rather than
  restored as garbage
- guarded storage access — Safari private mode and quota exhaustion both throw,
  and losing persistence must never break the canvas
- debounced autosave, so a burst of pen strokes is one write and not fifty
- a dispose function that genuinely unsubscribes

When they pass, reloading a session no longer loses the student's work.
