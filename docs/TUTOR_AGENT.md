# Tutor Agent Integration Guide

## Purpose

This document is the implementation contract for Mentora's whiteboard tutor.
It is intended for:

- the whiteboard owner capturing canvas context and rendering returned actions;
- the course-context owner maintaining retrieval behavior;
- the learning-engine owner consuming learning events; and
- backend agents extending prompts, schemas, or provider behavior.

Product behavior remains authoritative in `PRODUCT.md`. Shared architectural
constraints remain authoritative in `ARCHITECTURE.md`.

## Runtime flow

```text
Whiteboard multipart request
        ↓
FastAPI validates JSON + image signatures + 10 MB limits
        ↓
Korey's query_similar retrieves required course excerpts
        └── successful empty result on seeded course: expected-skill taxonomy fallback
        ↓
Google ADK Workflow
  single multimodal call
    ├── Canvas Analyst result → CanvasAnalysis
    └── mode-specific Tutor Planner result → TutorPlan
        ↓
Pydantic validation + deterministic safety policy
        ↓
TutorResponse with normalized canvas_actions
        ├── returned to whiteboard
        ├── learning events posted to optional webhook in background
        └── durable student model was read before agent execution
```

Gemini never calls tldraw. It can only produce the action types defined in
`backend/app/schemas/tutor.py`.

## Configuration

Create `backend/.env` from `backend/.env.example`. Tutor analysis requires all
of these values:

```text
GEMINI_API_KEY
OPENAI_API_KEY
PINECONE_API_KEY
PINECONE_INDEX_NAME
```

Optional settings:

```text
GEMINI_MODEL=gemini-3.5-flash-lite
TUTOR_REQUEST_TIMEOUT_SECONDS=8
TUTOR_RETRIEVAL_TOP_K=5
LEARNING_METRICS_WEBHOOK_URL=
LEARNING_METRICS_WEBHOOK_SECRET=
MENTORA_DB_PATH=
```

The OpenAI and Pinecone values belong to the existing course-context retrieval
pipeline. The Gemini key belongs only on the backend. Never put provider keys
in a `NEXT_PUBLIC_*` variable.

`GET /health` always remains available. It reports tutor `ready` or `not_ready`
and lists missing variable names, the selected model, and the total workflow
timeout, never secret values.

## Analyze endpoint

```text
POST /api/tutor/analyze
Content-Type: multipart/form-data
```

Fields:

| Field | Required | Description |
| --- | --- | --- |
| `payload` | yes | JSON string matching `TutorRequest` version `1.0`. |
| `canvas_image` | yes | Full canvas capture as PNG, JPEG, or WebP, maximum 10 MB. |
| `selection_image` | no | Crop corresponding to `selection.bounds`, using the same image formats and limit. |

The backend verifies image signatures. Renaming arbitrary data to `.png` is not
accepted.

For a PNG request, `canvas.image_width` and `canvas.image_height` must be the
positive integer pixel dimensions encoded in its IHDR header. Do not send
tldraw's logical export dimensions: its world-space bounds can be fractional.
Retain those world-space bounds separately so normalized response actions can
be mapped back onto the exact exported canvas region.

### Example payload

```json
{
  "schema_version": "1.0",
  "request_id": "ea0e25c0-91c9-4fe4-a990-e82686828b35",
  "user_id": "user_123",
  "course_id": "course_math_101",
  "session_id": "session_456",
  "problem_id": "problem_789",
  "mode": "hint",
  "trigger": "manual",
  "problem": {
    "prompt_text": "Differentiate f(x) = x^2.",
    "latex_blocks": ["f(x)=x^2"],
    "topic": "derivatives",
    "difficulty": "easy",
    "expected_skills": ["power rule"],
    "source": "generated"
  },
  "course": {
    "name": "MATH 101",
    "covered_topics": ["limits", "power rule"],
    "not_yet_covered_topics": ["L'Hopital's rule"],
    "notation_summary": "Use f'(x) notation.",
    "instructor_style_summary": "Short computational questions with visible steps."
  },
  "canvas": {
    "image_width": 2048,
    "image_height": 1536,
    "viewport": {
      "x": -120,
      "y": -80,
      "width": 1024,
      "height": 768,
      "zoom": 1.5
    },
    "shapes": [
      {
        "id": "shape_problem",
        "owner": "system",
        "shape_type": "text",
        "text": "Differentiate f(x) = x^2.",
        "bounds": {"x": 0.08, "y": 0.08, "width": 0.3, "height": 0.08}
      },
      {
        "id": "shape_student_1",
        "owner": "student",
        "shape_type": "draw",
        "bounds": {"x": 0.2, "y": 0.35, "width": 0.2, "height": 0.1}
      },
      {
        "id": "shape_ai_old",
        "owner": "ai",
        "shape_type": "text",
        "text": "Recall the power rule.",
        "bounds": {"x": 0.5, "y": 0.35, "width": 0.2, "height": 0.1}
      }
    ]
  },
  "selection": {
    "shape_ids": ["shape_student_1"],
    "bounds": {"x": 0.2, "y": 0.35, "width": 0.2, "height": 0.1}
  },
  "recent_interactions": [
    {
      "interaction_id": "interaction_previous",
      "mode": "mark",
      "summary": "The setup was marked correct."
    }
  ],
  "student_model": {
    "attempted_topics": ["derivatives"],
    "recurring_mistakes": ["power-rule coefficient"],
    "strengths": ["identifies polynomial structure"],
    "total_hints_used": 2
  },
  "transcript": "Can you give me a small hint?",
  "locale": "en-CA",
  "timezone": "America/Vancouver",
  "client_capabilities": {
    "supported_actions": ["text", "arrow", "circle", "check", "cross"],
    "supports_latex": true,
    "supports_selection_crop": true
  }
}
```

Send the JSON as one multipart string rather than flattening it into form
fields. For example:

```bash
curl http://localhost:8000/api/tutor/analyze \
  -F 'payload=<request.json' \
  -F 'canvas_image=@canvas.png;type=image/png' \
  -F 'selection_image=@selection.png;type=image/png'
```

## Response contract

Example:

```json
{
  "schema_version": "1.0",
  "interaction_id": "33c9fd11c4504fb588fa50490766cf88",
  "request_id": "ea0e25c0-91c9-4fe4-a990-e82686828b35",
  "status": "partial",
  "confidence": 0.91,
  "canvas_actions": [
    {
      "action_id": "f9209ab3b52641c89ca85a16a0494a6e",
      "type": "circle",
      "purpose": "focus_attention",
      "target": {"x": 0.2, "y": 0.35, "width": 0.2, "height": 0.1},
      "label": null
    },
    {
      "action_id": "02ddf308121b4e94ae75a8a1fc43ff0c",
      "type": "text",
      "purpose": "small_hint",
      "position": {"x": 0.43, "y": 0.35},
      "text": "What happens to the exponent?"
    }
  ],
  "summary": "A restrained power-rule hint.",
  "grounding_references": [
    {"filename": "lecture-3.pdf", "page": 4, "score": 0.94}
  ],
  "warnings": [],
  "course_boundary": {
    "requires_confirmation": false,
    "technique": null,
    "message": null,
    "alternatives_available": false
  },
  "learning_events": [],
  "learning_delivery": {"status": "disabled", "event_count": 0}
}
```

### Canvas actions

All coordinates are relative to the full submitted `canvas_image`, not the
tldraw viewport or world coordinate system.

| Type | Required geometry | Content |
| --- | --- | --- |
| `text` | `position: {x,y}` | `text` up to 240 characters |
| `math` | `position: {x,y}` | `latex` up to 500 characters |
| `arrow` | `start`, `end` | optional short `label` |
| `circle` | `target` bounds | optional short `label` |
| `underline` | `target` bounds | optional short `label` |
| `highlight` | `target` bounds | optional short `label` |
| `check` | `target` bounds | optional short `label` |
| `cross` | `target` bounds | optional short `label` |

Every normalized point is in `[0,1]`. A bounding box must have positive width
and height and remain inside the image. The backend returns at most 12 actions.

## Whiteboard integration notes for Jaden

1. Export the full analysis image, read its integer pixel dimensions from the
   PNG IHDR header, and retain the separate exact image-to-world transform.
2. Mark every structured shape with `system`, `student`, or `ai` ownership.
3. Convert tldraw shape bounds to normalized image bounds once when building the
   request.
4. If Select for AI is active, send both normalized selection bounds and the
   selected shape IDs. A crop improves attention but does not replace the full
   image.
5. Call one of the four backend modes; do not convert them into a generic
   instruction string.
6. Convert returned normalized action geometry through one renderer adapter.
7. Create controlled tldraw shapes with owner `ai` and attach
   `interaction_id`, `action_id`, and action type as metadata.
8. Persist AI shapes with the session and deduplicate repeated responses by
   `interaction_id` or the caller-generated `request_id`.

Successful Hint and Stuck responses should be appended to
`recent_interactions` for the next request. Failed requests do not count.
Clearing AI shapes is a presentation action and must not erase interaction or
assistance history. Hint sends `mode: "hint"`; I'm Stuck sends `mode: "stuck"`
so the planner applies its stronger scaffolding policy.

If `client_capabilities.supported_actions` is non-empty, the backend removes
unsupported actions and adds a warning. An empty list means the client supports
the complete version `1.0` action set.

Course grounding prefers uploaded Pinecone excerpts. When Pinecone responds
successfully with no matches for a validated seeded course (currently
`calc1`), the backend may use only the problem's taxonomy-compatible expected
skills and their direct prerequisites. The response includes a
`<course>-seeded-taxonomy` grounding reference and a warning so the fallback is
visible. A missing configured Pinecone index uses the same fallback for a
validated seeded course and is identified explicitly in the warning. Pinecone
authentication, network, rate-limit, and other exceptions still return `502`;
taxonomy data does not hide a provider outage.

## Tutor behavior and safety

- **Mark** evaluates completed work without revealing future steps.
- **Hint** gives the smallest useful spatial nudge.
- **Explain** gives a local course-grounded explanation.
- **Stuck** provides stronger scaffolding without needlessly finishing the
  problem.

The Canvas Analyst may return `uncertain`. In that case the service removes
checks/crosses, records no strength or mistake claims, and may return one short
clarification action.

If a proposed technique is outside the retrieved course boundary, all proposed
actions are replaced with a single confirmation message. The frontend should
present the returned `course_boundary` choice before requesting a follow-up
analysis that uses the new technique.

## Learning-engine contract for Ren

### Tutor observations versus completed attempts

Tutor analysis events describe what the agents observed during one
interaction. They remain available in `TutorResponse.learning_events` and may
be delivered to the optional webhook, but they do not update mastery.

Mastery changes only through:

```text
POST /api/courses/{course_id}/attempts
```

The attempt payload carries taxonomy-compatible `expected_skills`, numeric
difficulty, outcome, `hints_used`, and `stuck_requests`. Both assistance counts
default to zero. A correct attempt after any Stuck request receives the
multi-hint assistance score, and is never counted as correct-unassisted.

Before every tutor workflow, the backend loads the course-scoped student model
from SQLite. Skills with mastery at least `0.75` and confidence at least `0.5`
become strengths in the prompt snapshot; attempted skills, recurring
misconceptions, and completed-attempt hint totals are included as well.

SQLite defaults to `backend/mentora.db`. `MENTORA_DB_PATH` overrides the path,
and startup adds the backward-compatible `stuck_requests` column when an older
local database is detected.

### Learning observation delivery

Every supported learning observation is included in `learning_events` even
when webhook delivery is disabled. Fields include:

```text
schema_version, event_id, interaction_id, request_id
user_id, course_id, session_id, problem_id
tutor_mode, trigger, difficulty, occurred_at
type, topic, skill, outcome, evidence, mistake_tag, confidence
```

`type` is one of:

```text
strength | mistake | progress | help_usage
```

`outcome` is one of:

```text
correct | incorrect | partial | uncertain
```

Mistake observations require confidence of at least `0.6`. An overall uncertain
analysis cannot emit strength or mistake observations.

When `LEARNING_METRICS_WEBHOOK_URL` is configured, the backend sends:

```json
{
  "schema_version": "1.0",
  "interaction_id": "33c9fd11c4504fb588fa50490766cf88",
  "events": [
    {
      "schema_version": "1.0",
      "event_id": "669767aee5654196aa2499bbcb9d0827",
      "interaction_id": "33c9fd11c4504fb588fa50490766cf88",
      "request_id": "ea0e25c0-91c9-4fe4-a990-e82686828b35",
      "user_id": "user_123",
      "course_id": "course_math_101",
      "session_id": "session_456",
      "problem_id": "problem_789",
      "tutor_mode": "hint",
      "trigger": "manual",
      "difficulty": "easy",
      "type": "mistake",
      "topic": "derivatives",
      "skill": "power rule",
      "outcome": "incorrect",
      "evidence": "The derivative omits the coefficient 2.",
      "mistake_tag": "power-rule-coefficient",
      "confidence": 0.91,
      "occurred_at": "2026-08-22T20:00:00Z"
    }
  ]
}
```

Headers:

```text
Content-Type: application/json
X-Mentora-Event-Version: 1.0
X-Mentora-Signature: sha256=<hex digest>  # when a secret is configured
```

The signature is HMAC-SHA256 over the exact request body bytes. Compare it with
a constant-time function.

Delivery is intentionally non-durable for the hackathon. `queued` means a
background delivery was scheduled; it is not an acknowledgement from the
learning engine. `disabled` means no URL was configured or there were no
events. Background failure is logged without sensitive evidence and never
changes tutor success. `failed` is reserved by the schema for a future
synchronous status or durable delivery API. Consumers should deduplicate by
`event_id`.

## Errors

| Status | Meaning |
| --- | --- |
| `400` | An uploaded image is empty. |
| `413` | An image exceeds 10 MB. |
| `415` | Image format or signature is invalid. |
| `422` | `payload` violates the versioned request schema; the client shows a safe field path when available. |
| `502` | Required course retrieval or Gemini analysis failed. |
| `503` | One or more required integration settings are absent. |
| `504` | The configured tutor workflow timeout was reached. |

Responses do not expose provider errors, parser internals, course excerpts, or
secret values.

## Tests and extension points

Run deterministic tests:

```bash
cd backend
.venv/bin/python -m pytest -q
```

Run the opt-in Gemini fixture:

```bash
RUN_LIVE_GEMINI_TEST=1 .venv/bin/python -m pytest -q -m live
```

Add `-s` to print the validated analysis, plan, action count, and elapsed time:

```bash
RUN_LIVE_GEMINI_TEST=1 .venv/bin/python -m pytest -q -s -m live
```

The latency-critical workflow performs the Canvas Analyst and mode-specific
Tutor Planner roles in one Gemini request while preserving separate validated
`CanvasAnalysis` and `TutorPlan` objects. The default
`gemini-3.5-flash-lite` model uses minimal thinking, medium image resolution,
and a 1,024-token output ceiling. Full-canvas exports are capped at 1,280 pixels
on their longest edge. Provider `429` responses are not retried because quota
exhaustion cannot be repaired inside an interactive request; transient timeouts
and `5xx` responses still receive bounded SDK retries.

If the live test reports `RESOURCE_EXHAUSTED`, check the active model limits in
Google AI Studio or use a Gemini project with available quota. A successful
interaction normally consumes one model request; a malformed structured result
may consume one additional bounded repair request.

Main extension boundaries:

- `app/schemas/tutor.py`: versioned API and model-output contracts.
- `app/prompts/tutor.py`: analyst rules and mode-specific tutor behavior.
- `app/agents/tutor_workflow.py`: single-pass ADK agent, Gemini retries, and repair attempt.
- `app/services/tutor_context.py`: query construction and Korey retrieval.
- `app/services/tutor_service.py`: safety policy and response assembly.
- `app/services/learning_events.py`: webhook signing and delivery.

Changing action fields, coordinate semantics, ownership, or learning event
fields is a shared-contract change. Coordinate with Jaden or Ren and update
schemas, tests, this guide, and `ARCHITECTURE.md` together.
