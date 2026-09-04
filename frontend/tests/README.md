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
| `animate.test.ts` / `animateActions.test.ts` | Progressive stroke/typewriter rendering and cancellable tutor-action sequences |
| `api.test.ts` | `lib/api/api.ts` — multipart construction, error mapping |
| `analyze.test.ts` | `lib/tutor/analyze.ts` — capture → request → render, with only the network faked |
| `persistence.test.ts` | `lib/canvas/persistence.ts` — key scoping, versioned envelope, guarded storage, debounced autosave |
| `spaces.test.ts` | `lib/spaces/store.ts` — the space index |
| `wav.test.ts` | `lib/voice/wav.ts` — the RIFF header the backend sniffs, and PCM conversion |
| `microphone.test.ts` | `lib/voice/microphone.ts` — permission, stop, cancel, and track release |
| `voiceCapture.test.ts` | `lib/voice/voiceCapture.ts` — the recording lifecycle and its teardown |
| `voiceControl.test.ts` | `features/tutor/VoiceControl.tsx` — what each state says out loud |
| `useVoiceCapture.test.ts` | `lib/voice/useVoiceCapture.ts` — the hook under `StrictMode` effect replay |

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

## The microphone invariant

Voice is an input to the canvas tutor, so its failure modes are about hardware
rather than tutoring. Two rules carry the weight, and both are tested:

1. **No path leaves a track running.** Stop, cancel, a recorder that fails
   mid-flight, a permission prompt answered after the student gave up, and
   unmount all release the `MediaStream`. A live track is a recording indicator
   the student cannot turn off.
2. **An abandoned recording never reaches the tutor.** Every async step checks
   the attempt it belongs to, so a transcript that arrives after a cancel or an
   unmount is dropped rather than submitted.

`useVoiceCapture.test.ts` is the only test that renders through React, because
one bug only exists there: Strict Mode replays effects, so a teardown that
retired the machine permanently left the microphone inert in development while
every unit test still passed. It stubs the browser APIs rather than the
module's dependencies, so it fails if the path from the button to
`getUserMedia` breaks anywhere along it.
