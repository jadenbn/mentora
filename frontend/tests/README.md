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
| `persistence.test.ts` | `lib/canvas/persistence.ts` — key scoping, versioned envelope, guarded storage, debounced autosave |

## The coordinate invariant

Most of the value here is on one seam. The backend answers in coordinates
normalized to the submitted image; the renderer is the only place that converts
them back to tldraw world space. `capture.test.ts` and
`renderCanvasActions.test.ts` pin both directions against a frame whose origin
is deliberately not `(0,0)`, so an implementation that forgets the offset fails
rather than coincidentally passing.

## Canvas persistence

`lib/canvas/persistence.ts` stores one versioned envelope per session in
localStorage. The tests pin the behaviour that is easy to get subtly wrong:

- a snapshot written by a newer format is ignored, not restored as garbage
- every storage path is guarded — Safari private mode and quota exhaustion both
  throw, and losing persistence must never break the canvas
- autosave is trailing-edge debounced, so a burst of fifty strokes is one write
- dispose cancels a write that was already queued, so navigating away mid-stroke
  cannot fire a save after teardown
- a failed write leaves the subscription intact for the next change
