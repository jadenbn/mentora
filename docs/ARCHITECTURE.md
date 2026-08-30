# ARCHITECTURE.md
## Purpose
This document defines the current technical direction and major system boundaries.
It is intentionally less detailed than a final production design.
For product behavior, read `PRODUCT.md`.
For agent workflow and branch rules, read `../AGENTS.md`.

**This document describes direction, some of which is not built.** For the
shapes that actually cross the wire today, `TUTOR_AGENT.md` and
`backend/app/schemas/tutor.py` are authoritative and win any disagreement with
this file. Sections that describe unbuilt work say so inline.

## 1. Architectural Goals
Optimize for:
1. reliable end-to-end demo
2. clean boundaries for six parallel workstreams
3. fast local development
4. low integration friction
5. persistent whiteboard sessions
6. structured AI-to-canvas communication
7. course-aware behavior
8. web/iPad compatibility
9. replaceable AI/rendering internals
Avoid premature complexity and microservices.

## 2. Settled Stack
Frontend:
```text
TypeScript
React
Next.js
tldraw
```
Primary runtime: web, especially iPad Safari.
Backend:
```text
Python 3.12+
FastAPI
Pydantic v2
uvicorn
```
Frontend packages are managed with Bun (`frontend/bun.lock`).

## 3. High-Level System
```text
┌───────────────────────────────────────┐
│ React / Next.js / tldraw              │
│ Course UI                             │
│ Session grid                          │
│ Infinite whiteboard                   │
│ Problem rendering                     │
│ Tutor controls                        │
│ Select for AI                         │
│ Annotation renderer                   │
└──────────────────┬────────────────────┘
                   │ HTTP / JSON / uploads
                   ▼
┌───────────────────────────────────────┐
│ FastAPI                               │
│ Tutor / Vision                        │
│ Course ingestion                      │
│ Retrieval / Course Context            │
│ Question generation                   │
│ Persistence                           │
│ Student model                         │
└─────────┬──────────┬──────────┬───────┘
          ▼          ▼          ▼
       AI APIs    Storage    Search/vector layer
```

## 4. Repository Shape
Preserve an existing sensible structure.
If starting fresh:
```text
/
├── AGENTS.md
├── README.md
├── docs/
│   ├── PRODUCT.md
│   └── ARCHITECTURE.md
├── frontend/
│   ├── app/
│   ├── components/
│   ├── features/
│   ├── lib/
│   └── types/
└── backend/
    ├── app/
    │   ├── main.py
    │   ├── api/
    │   ├── schemas/
    │   ├── services/
    │   ├── prompts/
    │   ├── models/
    │   └── utils/
    └── tests/
```
Do not reorganize the entire repo for aesthetics.

## 5. Core Domain Model
Conceptual entities:
```text
User
Course / Space
Course Document
Whiteboard Session
Canvas State
Problem
Tutor Interaction
Student Model
```
Relationship:
```text
User
 └── Course
      ├── Course Documents
      └── Whiteboard Sessions
           ├── Problem
           ├── Canvas State
           └── Tutor Interactions
```
A session may contain a generated or imported problem. Generated problems are
stored in backend SQLite and copied into the local Space record for restore.

## 6. Course
A Course owns documents, style/coverage metadata, whiteboard sessions, and course-level student progress.
Conceptual representation:
```json
{
  "id": "course_123",
  "name": "MATH 101",
  "created_at": "...",
  "settings": {}
}
```

## 7. Whiteboard Session
A session is a persistent working document. Called a **space** in the UI and in
the frontend code, and currently stored in browser localStorage rather than on
the server. The current Space record stores the problem association alongside
its canvas.
Conceptual representation:
```json
{
  "id": "session_123",
  "course_id": "course_123",
  "title": "Integration Practice 4",
  "problem_id": "problem_456",
  "created_at": "...",
  "updated_at": "...",
  "preview_image": "optional",
  "canvas_state": "..."
}
```
The canvas must be restorable. Preview images are not canonical state.

## 8. Canvas State
Use supported tldraw serialization/persistence mechanisms where practical.
Preserve student strokes, system/problem shapes, AI shapes, positions, styles, and useful metadata.
Camera/viewport state may also be stored.
Avoid inventing a parallel graphics document model unless necessary.

## 9. Shape Ownership
At minimum:
```text
system
student
ai
```
Potential metadata:
```ts
type ShapeOwner = "system" | "student" | "ai";
```
Shapes the tutor draws carry `owner: "ai"` and the `interaction_id` that
produced them. Each response is also stored as a per-Space feedback layer in
browser storage; the selected layer is rendered and switching layers replaces
AI shapes without disturbing system or student content. Ownership no longer
crosses the wire as a shape list: capture excludes tutor-authored shapes from
the image and sends their bounds as `prior_annotations`.
The critical invariant is that the system can distinguish what the problem said, what the student wrote, and what the AI wrote.

## 10. Frontend Responsibilities
Frontend owns:
- course navigation
- session grid
- tldraw lifecycle
- whiteboard interactions
- problem display
- structured annotation rendering
- Select for AI
- canvas capture/export
- tutor controls
- live-tutor timing/detection where appropriate
Keep backend access behind a small API/client layer.
Do not call private AI-provider APIs directly from browser code.

Whiteboard controls remain canvas-adjacent rather than becoming a second
workspace: drawing styles open from a palette button in the left tool rail, and
tutor actions fan out from the right-edge control. Starting a tutor request
collapses the action fan and exposes a transient navbar status. The current
feedback summary lives in that navbar; spatial marks alone live on the canvas.

## 11. Backend Responsibilities
Backend owns:
- provider credentials
- tutor AI calls
- multimodal analysis
- course ingestion
- document-processing orchestration
- retrieval
- question generation
- persistence APIs
- student-model logic
- validation
Prefer thin FastAPI routes and service modules.

## 12. Suggested Backend Services
Possible services:
```text
tutor_service.py
question_service.py
course_service.py
document_service.py
session_service.py
student_model_service.py
```
Potential support areas:
```text
retrieval/
prompts/
providers/
```
Follow existing conventions if the repository already has them.

## 13. API Shape
Possible routes:
```text
GET  /health                                  implemented
POST /api/tutor/analyze                       implemented
POST /api/courses/{course_id}/documents       implemented
POST /api/courses/{course_id}/questions/generate implemented
GET  /api/courses/{course_id}/search          implemented
GET  /api/courses
POST /api/courses
GET  /api/courses/{course_id}
GET  /api/courses/{course_id}/sessions
POST /api/courses/{course_id}/sessions
GET  /api/sessions/{session_id}
PUT  /api/sessions/{session_id}
POST /api/problems/import
GET  /api/courses/{course_id}/student-model
```

The implemented course routes support document upload/listing and grounded
question generation. Sessions ("spaces" in the UI) live in
browser localStorage, not on the server, so there is no session endpoint.
Prefer domain operations over one endpoint per prompt.

## 14. Shared Schemas
Use Pydantic on the backend and corresponding TypeScript types on the frontend.
When changing a shared schema:
- update backend model
- update frontend type
- update API client/callers
- update tests
- coordinate with affected teammates

## 15. Tutor Request

`POST /api/tutor/analyze` is multipart form data:

```text
course_id          retrieval scope (carried; retrieval is deferred)
mode               mark | hint | explain | stuck
canvas_image       optional PNG/JPEG/WebP; maximum 10 MB when present
prior_annotations  JSON array of normalized bounds; defaults to []
problem_context    optional validated ProblemContext JSON
```

Five fields at most, no JSON request body. Normal work-analysis requests send
an image, three scalars, and optionally the exact structured problem separately
from the image. An `stuck` request with `problem_context` may omit the image;
the tutor then reasons from the structured question and course grounding alone.

Tutor-authored shapes are excluded from the exported image and their positions
are sent as `prior_annotations` instead, so the model cannot read its own
handwriting back as student work. See `TUTOR_AGENT.md`.

## 16. Tutor Modes
Backend-facing enum:
```text
mark
hint
explain
stuck
```
Prompt/service behavior must differ by mode.

## 17. Structured Tutor Response

```text
interaction_id   server-minted; the renderer keys shape replacement on it
status           correct | incorrect | partial | uncertain
canvas_actions   at most 12
summary          short plain-language explanation
```

`canvas_actions` contains target actions: `highlight`, `circle`, `check`, or
`cross`, each pointing at a normalized box. Prose is never a canvas action; the
required, concise `summary` is shown in the navbar instead and rendered as a
single KaTeX document, including its prose. Highlights are optional and the
array may contain multiple independent highlight targets.

Gemini output is schema-constrained, then validated independently with
Pydantic, then passed through a deterministic safety policy. The renderer never
receives arbitrary tldraw operations.

The invariant remains: **validated structured output before tldraw rendering**.

The frontend stores the last 10 validated responses per Space as feedback
layers in local storage. The navbar exposes immediate previous/next navigation
and a visibility toggle; navigation changes only AI-owned shapes and never
removes student or system shapes. A new response always selects the newest
layer.

## 18. Coordinates
Prefer normalized image-space coordinates at the AI/API boundary:
```text
x ∈ [0,1]
y ∈ [0,1]
```
Example:
```json
{"x": 0.51, "y": 0.63, "width": 0.08, "height": 0.05}
```
Convert to tldraw/world coordinates in one well-defined frontend adapter.
Do not scatter conversion logic.

## 19. Annotation Renderer
Frontend owns:
```text
CanvasAction
      ↓
Annotation Renderer
      ↓
tldraw operations
```
The renderer creates controlled highlights, circles, checks, and crosses — the
four implemented actions. `TutorAnnotation` was an earlier name for this and
no longer exists. The whiteboard uses a progressive renderer for tutor
feedback: circles, checks, and crosses are emitted as freehand draw-shape
points at a capped rate, while highlights appear immediately. Animation is
presentation-only,
ignores the undo history, can be cancelled on teardown, and does not change the
validated tutor contract or ownership metadata.

## 20. Canvas Capture
Expose a clean frontend boundary conceptually like:
```ts
async function captureCanvasForAnalysis(): Promise<Blob>
```
Hide low-level tldraw export details from unrelated code.
Where useful, send image plus structured metadata.

## 21. Select for AI
Conceptual representation:
```ts
interface AiSelection {
  shapeIds: string[];
  bounds: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
}
```
Experiments can determine whether tutor requests benefit most from selected IDs, bounds, a crop, the full image, or a combination.

## 22. Multimodal Analysis
Initial approach:
```text
canvas snapshot
    + metadata
    + problem text
    + course context
        ↓
multimodal model
        ↓
structured tutor response
```
Dedicated OCR is optional and should be added only if experiments show clear value.

## 23. Course Ingestion
Initial pipeline:
```text
upload
  ↓
store document
  ↓
extract content
  ↓
chunk / structure
  ↓
attach metadata
  ↓
store canonical text in SQLite
  ↓
index vector IDs and scope metadata in Pinecone
  ↓
retrieve
```
Useful metadata:
```text
course_id
document_id
filename
page
document_type
topic
content
```
Potential document types:
```text
lecture
assignment
exam
practice_exam
syllabus
formula_sheet
other
```

## 24. Retrieval
SQLite is canonical for documents, chunks, generated problems, and
problem-to-chunk grounding. Pinecone stores vector IDs and scope metadata;
retrieval joins ranked IDs back to SQLite text. Small documents use full
context, while larger documents use semantic retrieval. Extraction, indexing,
and semantic search run in worker threads so FastAPI's event loop stays free.

## 25. Course Style Model
Style may include:
```text
notation
question wording
difficulty
format
topic distribution
subquestion patterns
answer expectations
```
For the hackathon, style can be inferred on demand, summarized during ingestion, stored as a course profile, or a hybrid.
Choose the simplest approach that produces convincing results.

## 26. Question Generation
Inputs may include:
```text
course_id
topic
difficulty
user overrides
retrieved examples
course style profile
covered-topic constraints
```
Current endpoint: `POST /api/courses/{course_id}/questions/generate` accepts a
document ID and short question request. The direct `google-genai` workflow
returns a validated plan, checks grounding IDs against retrieved chunks, and
persists the generated problem and its grounding in SQLite.

Response:
```json
{
  "id": "problem_123",
  "topic": "integration-by-parts",
  "difficulty": "medium",
  "prompt": "Evaluate ...",
  "expected_skills": ["integration-by-parts"],
  "source": "generated"
}
```
Do not couple generation to one canvas representation.

## 27. Imported Problem Reconstruction
Pipeline:
```text
image/PDF
   ↓
multimodal extraction
   ↓
structured problem representation
   ↓
validation
   ↓
clean frontend rendering
```
Conceptual representation:
```json
{
  "source": "imported",
  "prompt_text": "...",
  "figures": [],
  "metadata": {}
}
```
Imported-problem reconstruction is not built. Generated problems render
directly on the canvas as locked system-owned tldraw shapes using KaTeX, with a
readable fallback for malformed LaTeX. Capture excludes system shapes while
`problem_context` preserves the complete question for Gemini.
The key boundary is: recognize first, render cleanly second.

## 28. Persistence
At minimum store:
```text
course
session metadata
canvas document state
problem association
timestamps
```
Optionally:
```text
tutor interactions
student-model updates
preview image
camera/viewport state
```
Spaces use browser localStorage for now; course documents, chunks, generated
problems, and grounding use SQLite. Pinecone is an index, never the canonical
text store.

## 29. Autosave
Desired UX is automatic persistence.
Possible flow:
```text
canvas changes
   ↓
debounce
   ↓
save session state
```
Avoid server writes on every pen point.
Combining local immediate state with debounced server save is reasonable.

## 30. Preview Thumbnails
Session cards can use generated canvas previews.
Thumbnails are convenience data, not the persistent canvas source of truth.

## 31. Live Tutor
Modes:
```text
instant
two_seconds
new_line
```
Likely flow:
```text
student modifies canvas
    ↓
frontend trigger logic
    ↓
tutor analysis request
    ↓
backend analysis
    ↓
annotations
```
Do not call the model literally on every stroke.
For Instant, use practical debounce.
For 2 Seconds, inactivity detection is straightforward.
For New Line, a heuristic is acceptable initially.

## 32. Voice
Potential flow:
```text
audio
  ↓
speech-to-text
  ↓
transcript + selected canvas + course/problem context
  ↓
tutor service
```
Treat transcript as contextual instruction, not a separate chat architecture.

## 33. Student Model
MVP signals may include:
```text
topic
attempt outcome
hint count
mode usage
mistake tags
difficulty
timestamp
```
Do not make the core tutor loop depend on a sophisticated model.

Learning events are not emitted yet. The tutor observes plenty worth
recording, but the learning engine wants closed-vocabulary, slug-identified,
float-typed facts and the tutor produces prose. That adapter is a design
decision rather than a merge, and it waits until the canvas loop works.

## 34. Built-In Course
Support at least one built-in demo course, likely Calculus I.
Where practical, seed it through the same Course Context mechanisms as uploaded courses to avoid a separate architecture.

## 35. AI Provider Boundary
Avoid scattering provider SDK calls.
Prefer:
```text
Tutor/Question Service
      ↓
Provider Adapter
      ↓
AI SDK
```
Centralize timeouts, retries, and structured-output handling without building an enterprise abstraction framework.

The tutor is one direct Gemini call through the `google-genai` SDK:

```text
canvas image + mode + prior annotations
        ↓
Gemini multimodal generation (TutorPlan response schema)
        ↓ independent Pydantic validation and safety policy
TutorResponse
```

Reading the canvas and deciding what to draw are the same judgement, so
splitting them only bought a second round trip on the path where
responsiveness is the product.

The SDK performs up to three bounded transient HTTP attempts for 408 and
5xx responses. The application makes one additional request only when
structured output is malformed. The model defaults to
`gemini-3.5-flash-lite` and is replaceable through `GEMINI_MODEL`; thinking
defaults to `low` and is replaceable through `GEMINI_THINKING_LEVEL`. These
settings are shared by tutoring and grounded question generation.

## 36. Prompt Organization
Possible layout:
```text
backend/app/prompts/
    tutor.py
    question_generation.py
    course_analysis.py
    problem_import.py
```
Prompts should encode role, tutor mode, course constraints, output schema, selected context, answer-restraint behavior, and uncertainty behavior.

## 37. Course Boundary Check
Possible flow:
```text
proposed technique
    ↓
compare against course coverage
    ↓
clearly covered → continue
uncertain/not covered → return warning
```
Potential response:
```json
{
  "requires_course_boundary_confirmation": true,
  "technique": "integration by parts",
  "synopsis": "...",
  "alternatives_available": true
}
```
The algorithm can be approximate for the hackathon.

Not implemented. The check needs to know what the course has covered, which
means course retrieval, which is deferred — so a boundary decision today would
be the model guessing. It returns with retrieval.

## 38. Error Handling
Plan for:
```text
timeout
rate limit
malformed AI output
empty response
upload failure
retrieval failure
model uncertainty
persistence failure
```
One failed AI call must not corrupt the session.

## 39. Duplicate Tutor Calls
Live tutor/retries can produce duplicates.
Where useful, include interaction/request IDs and associate AI shapes with an interaction ID.
Prevent obvious duplicate annotations without over-engineering distributed idempotency.

## 40. Performance
Watch:
- oversized canvas images
- oversized prompts
- excessive retrieval context
- redundant model calls
- repeated parsing
- serial work that can safely be parallelized
Compress/resize images if quality remains sufficient.
Optimize the core tutoring loop first.

## 41. Security
Keep secrets server-side.
Validate uploads.
Treat model output as untrusted.
Do not execute arbitrary model instructions.
Avoid logging sensitive course content unnecessarily.

Tutor readiness requires `GEMINI_API_KEY` and nothing else. `/health` and
configuration errors report missing variable names only. Image type is verified
from file signatures rather than trusting multipart headers.

## 42. Testing
Prioritize deterministic tests for:
```text
Pydantic schemas
annotation validation
coordinate conversion
session serialization
retrieval helpers
question schemas
course-boundary helpers
student-model updates
```
Manual integration test:
```text
course
 ↓
session
 ↓
problem
 ↓
student writes
 ↓
tutor request
 ↓
AI response
 ↓
annotation renders correctly
 ↓
reload
 ↓
state persists
```

## 43. Deployment
Keep deployment simple:
```text
Next.js frontend
FastAPI backend
managed storage/database
AI provider APIs
```
A stable public demo URL is more valuable than infrastructure experimentation.

## 44. Architecture Anti-Goals
Avoid:
- microservices
- multiple canvas implementations
- provider-specific calls scattered everywhere
- private keys in the frontend
- screenshot-only persistence
- raw LLM-to-canvas execution
- tightly coupling tutor reasoning to handwriting/rendering style

## 45. Decision Heuristics
Prefer implementations that:
- preserve shared contracts
- minimize merge conflicts
- keep AI output structured
- make the core demo reliable
- are easy for teammates to understand
- work in desktop browsers and iPad Safari
- avoid unnecessary infrastructure
- keep frontend/backend responsibilities clear

## 46. End-State Mental Model
```text
Course documents
      ↓
Course model/context
      ↓
Question generation / tutor grounding
      ↓
Persistent tldraw session
      ↓
Student handwritten work
      ↓
Canvas capture + structured context
      ↓
FastAPI tutor service
      ↓
Multimodal model
      ↓
Validated annotation intent
      ↓
Frontend annotation renderer
      ↓
Persistent AI feedback on canvas
      ↓
Student-model signal
```
If the architecture supports this cleanly, it is serving the product.
