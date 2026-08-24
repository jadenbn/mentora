# Tutor Agent

The implementation contract for Mentora's whiteboard tutor.

**This file is authoritative for the shapes that cross the wire today.**
`PRODUCT.md` holds product intent and `ARCHITECTURE.md` holds direction; where
either disagrees with this file or with `backend/app/schemas/tutor.py`, this
file and the schema win.

## The loop

```text
student draws  ->  taps a mode button
        |
capture: student's shapes only, exported as one PNG
        |
problem + its recorded source chunks are loaded separately
        |
POST /api/tutor/analyze   (multipart)
        |
one Gemini call: read the canvas, plan the annotations
        |
Pydantic validation + deterministic safety policy
        |
TutorResponse -> renderCanvasActions draws it
```

Gemini never touches tldraw. It can only produce the actions in
`backend/app/schemas/tutor.py`.

## Configuration

One required credential:

```text
GEMINI_API_KEY
```

Optional: `GEMINI_MODEL` (default `gemini-3.7-flash`),
`TUTOR_REQUEST_TIMEOUT_SECONDS` (default 45), and `MENTORA_DB_PATH`.

`GET /health` is always available and reports missing variable *names*, never
values.

## Request

```text
POST /api/tutor/analyze
Content-Type: multipart/form-data
```

| Field | Required | Description |
| --- | --- | --- |
| `course_id` | yes | Course and grounded-problem scope. |
| `mode` | yes | `mark`, `hint`, `explain`, or `stuck`. |
| `canvas_image` | yes | PNG, JPEG, or WebP. Maximum 10 MB. |
| `prior_annotations` | no | JSON array of normalized bounds. Defaults to `[]`. |
| `problem_context` | no | JSON generated-problem entity. Defaults to absent. |

Image type is determined from the file signature. A declared `Content-Type`
that contradicts the bytes is refused.

### prior_annotations

The tutor's own marks live on the same canvas as the student's work. Two rules
keep the model from grading its own handwriting:

1. Tutor-authored and system/problem shapes are **excluded from the exported
   image**. The picture contains only student work, by construction.
2. Their **positions are sent separately**, so follow-up feedback still knows
   where it has already written.

### problem_context

The browser sends the visible generated problem as structured JSON, separate
from the canvas image. The backend uses its id to load the exact document
chunks recorded when the question was generated. If that record is missing or
SQLite retrieval fails, the supplied prompt remains usable without excerpts.

## Response

```json
{
  "interaction_id": "33c9fd11c4504fb588fa50490766cf88",
  "status": "partial",
  "canvas_actions": [
    {"type": "text", "position": {"x": 0.43, "y": 0.35}, "text": "What about the 2?"},
    {"type": "circle", "target": {"x": 0.2, "y": 0.35, "width": 0.2, "height": 0.1}}
  ],
  "summary": "The setup is right; the coefficient was dropped."
}
```

`status` is `correct`, `incorrect`, `partial`, or `uncertain`.

### Actions

Two shapes, because there are two things the tutor can do to a canvas.

| Type | Carries | Draws |
| --- | --- | --- |
| `text` | `position` | words beside the work |
| `circle` | `target` | an outline around a region |
| `check` | `target` | a ✓ past the region's top-right |
| `cross` | `target` | a ✗ past the region's top-right |

All coordinates are normalized to the submitted image, `[0, 1]` from its
top-left. `frontend/lib/annotations/renderCanvasActions.ts` is the only place
that converts them to tldraw world space.

`interaction_id` is server-minted. Re-rendering the same interaction replaces
its shapes; a different interaction leaves earlier feedback in place.

## The safety policy

`app/services/tutor_policy.py`. Pure: a plan in, a plan out.

- **Uncertain work is never graded.** When the model returns `uncertain`, every
  `check` and `cross` is stripped. If nothing is left, a request for
  clarification is substituted.
- **At most 12 actions.** Over-eager plans are truncated rather than rejected,
  so one long answer does not cost a repair round trip.

## Errors

| Status | Meaning |
| --- | --- |
| 400 | the image was empty |
| 413 | the image exceeded 10 MB |
| 415 | not a PNG/JPEG/WebP, or the declared type contradicts the bytes |
| 422 | bad mode, missing course, malformed annotations/problem, or course mismatch |
| 502 | the provider failed |
| 503 | the server is not configured; the body names the missing variables |
| 504 | the provider did not answer in time |

Provider messages are never echoed to the client — they can quote credentials
and prompt fragments.

## Deferred

Not built:

- **Arbitrary course retrieval.** Generated problems reuse the exact chunks
  chosen during generation; free-form semantic search across every course
  material remains deferred.
- **Learning events.** The tutor observes plenty worth recording; the learning
  engine on `ren/learning-engine` wants closed-vocabulary, slug-identified,
  float-typed facts. That adapter is a design decision, not a merge.
- **Voice context.** Folds in as another input to the single model call.

## Extension points

- `app/schemas/tutor.py` — the wire contract.
- `app/prompts/tutor.py` — mode policy and the allowed action set.
- `app/services/tutor_policy.py` — what is safe to render.
- `app/agents/tutor_workflow.py` — tutor provider adapter.
- `app/agents/question_workflow.py` — grounded-question provider adapter.

Changing an action's fields, coordinate semantics, or the allowed set is a
breaking change on both sides of the wire. `ALLOWED_ACTIONS` and the renderer
are pinned together by `backend/tests/test_prompts.py`.
