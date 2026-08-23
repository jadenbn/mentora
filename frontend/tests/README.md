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
| `capture.test.ts` | `lib/canvas/capture.ts` — normalization, export scope, prior annotations |
| `renderCanvasActions.test.ts` | `lib/annotations/renderCanvasActions.ts` — the four action types, coordinate conversion, provenance |
| `api.test.ts` | `lib/api/api.ts` — multipart construction, error mapping |
| `analyze.test.ts` | `lib/tutor/analyze.ts` — capture → request → render, with only the network faked |
| `persistence.test.ts` | `lib/canvas/persistence.ts` — key scoping, versioned envelope, guarded storage, debounced autosave |
| `spaces.test.ts` | `lib/spaces/store.ts` — the space index |

## The coordinate invariant

Most of the value here is on one seam. The backend answers in coordinates
normalized to the submitted image; the renderer is the only place that converts
them back to tldraw world space. `capture.test.ts` and
`renderCanvasActions.test.ts` pin both directions against a frame whose origin
is deliberately not `(0,0)` and whose aspect ratio is not 1:1, so an
implementation that forgets the offset or the scale fails rather than
coincidentally passing.

## The follow-up tutoring invariant

The tutor's own annotations live on the same canvas as the student's work, so
on a second request the model can read its own handwriting back and grade it as
if the student wrote it.

Two rules prevent that, and both are tested:

1. **AI-authored shapes are excluded from the exported image.** The student's
   work is the only thing in the picture, by construction rather than by asking
   the prompt nicely.
2. **Their positions are sent separately** as `prior_annotations`, so the model
   still knows where it has already written and can build on it.

A canvas holding only prior feedback therefore has nothing to analyze, and
`analyze.test.ts` asserts it is refused without a network call.
