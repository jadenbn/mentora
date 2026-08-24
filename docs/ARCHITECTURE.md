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
Exact package tooling may follow repository setup.

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
A session may contain a generated or imported problem.

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
the server. A generated problem is stored with the local space and rendered as
a locked system-owned note; its canonical grounding record lives in SQLite.
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
produced them, which is how re-rendering one interaction replaces its own
shapes without disturbing earlier feedback. Ownership no longer crosses the
wire as a shape list: the capture excludes tutor-authored shapes from the
image and sends their bounds as `prior_annotations`.
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
GET  /api/courses/{course_id}/documents       implemented
POST /api/courses/{course_id}/questions/generate implemented
GET  /api/courses
POST /api/courses
GET  /api/courses/{course_id}
GET  /api/courses/{course_id}/sessions
POST /api/courses/{course_id}/sessions
GET  /api/sessions/{session_id}
PUT  /api/sessions/{session_id}
POST /api/questions/generate
POST /api/problems/import
GET  /api/courses/{course_id}/student-model
```

The marked document, question, health, and tutor routes exist. Sessions
("spaces" in the UI) live in
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
course_id          course and grounded-problem scope
mode               mark | hint | explain | stuck
canvas_image       PNG, JPEG, or WebP; maximum 10 MB
prior_annotations  JSON array of normalized bounds; defaults to []
problem_context     optional JSON generated-problem entity
```

The browser sends the student image and small scalar/JSON fields. The backend
loads recorded document excerpts by problem id; course material never crosses
the browser tutor boundary.

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

`canvas_actions` is a discriminated union of two shapes: `text` says something
at a normalized point, and `circle` / `check` / `cross` point at a normalized
box. There is no third shape, and no action carries a label — text is the one
way to put words on a canvas.

Gemini output is schema-constrained, then validated independently with
Pydantic, then passed through a deterministic safety policy. The renderer never
receives arbitrary tldraw operations.

The invariant remains: **validated structured output before tldraw rendering**.

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
The renderer creates controlled text, circles, checks, and crosses — the four
implemented actions. `TutorAnnotation` was an earlier name for this and no
longer exists.
This boundary also enables future handwriting animation without changing tutor reasoning.

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
Implemented pipeline:
```text
upload
  ↓
extract content
  ↓
chunk / structure
  ↓
attach metadata
  ↓
transactional SQLite document/chunk storage
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

## 24. Recorded Context

There is no embedding index in the current implementation. Question generation
receives labelled chunks from one selected document and records the one to eight
chunk ids that support its output. Tutor interactions reuse those exact chunks,
which avoids an extra retrieval/model round trip and prevents semantic search
from omitting context required by a problem Mentora generated itself.

Arbitrary cross-document queries may later use embeddings or managed File
Search, but that is a separate capability rather than a prerequisite here.

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
Implemented input is a course id plus one document id. Gemini receives up to a
160,000-character, source-labelled context; oversized documents use distributed
beginning/middle/end windows. Structured provider output supplies the visible
prompt plus validated source chunk ids. Public response:
```json
{
  "id": "problem_123",
  "prompt": "Evaluate ...",
  "source": "generated",
  "document_id": "doc_123"
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
Problem import is not built. Generated problems do use a structured record and
are excluded from the canvas image; an eventual imported problem must join that
same boundary rather than making the tutor infer it from student pixels.
The key boundary is: recognize first, render cleanly second.

## 28. Persistence
At minimum store:
```text
course
session metadata
canvas document state
problem association
timestamps
course documents and ordered extracted chunks
generated problems and ordered grounding-chunk links
```
Optionally:
```text
tutor interactions
student-model updates
preview image
camera/viewport state
```
Use hackathon-appropriate storage. Product semantics matter more than database sophistication.

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

The tutor is one Gemini call through a single ADK agent:

```text
canvas image + mode + prior annotations
        ↓
LlmAgent (Gemini multimodal, TutorPlan response schema)
        ↓ independent Pydantic validation and safety policy
TutorResponse
```

Reading the canvas and deciding what to draw are the same judgement, so
splitting them only bought a second round trip on the path where
responsiveness is the product.

ADK performs up to three bounded transient HTTP attempts. The application makes
one additional attempt only when structured output is malformed. The model
defaults to `gemini-3.7-flash` and is replaceable through `GEMINI_MODEL`.

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

Not implemented. Recorded excerpts ground one generated problem, but they are
not yet a course-wide coverage model, so a boundary decision today would still
be the model guessing.

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

Tutor and question-generation readiness require `GEMINI_API_KEY` and nothing else. `/health` and
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
