# ARCHITECTURE.md
## Purpose
This document defines the current technical direction and major system boundaries.
It is intentionally less detailed than a final production design.
For product behavior, read `PRODUCT.md`.
For agent workflow and branch rules, read `../AGENTS.md`.

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
A session is a persistent working document.
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
Optional metadata may include `session_id`, `interaction_id`, `annotation_type`, or `problem_id`.
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
GET  /health
GET  /api/courses
POST /api/courses
GET  /api/courses/{course_id}
GET  /api/courses/{course_id}/sessions
POST /api/courses/{course_id}/sessions
GET  /api/sessions/{session_id}
PUT  /api/sessions/{session_id}
POST /api/courses/{course_id}/documents
POST /api/questions/generate
POST /api/problems/import
POST /api/tutor/analyze
POST /api/courses/{course_id}/attempts
GET  /api/courses/{course_id}/student-model
GET  /api/courses/{course_id}/next-problem-spec
```
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

`POST /api/tutor/analyze` is implemented as multipart form data:

```text
payload          JSON TutorRequest, schema_version 1.0
canvas_image     required PNG, JPEG, or WebP; maximum 10 MB
selection_image  optional crop of the selected region
```

`TutorRequest` includes request/user/course/session/problem identifiers, tutor
mode and trigger, structured problem and course metadata, canvas dimensions and
viewport, shapes with `system|student|ai` ownership, normalized selection,
recent tutor interactions, student-model snapshot, optional transcript or
instruction, locale, timezone, and renderer capabilities.

The browser sends identifiers and compact structured context. The backend
retrieves the relevant course excerpts through the existing course-context
service; large document context is never sent repeatedly by the browser.
Pinecone excerpts remain authoritative. If Pinecone succeeds but returns no
matches for a course with a validated seed taxonomy, the backend grounds the
request in only the problem's expected skills and their direct prerequisites.
The response identifies that fallback in both `warnings` and
`grounding_references`. Retrieval/provider failures never silently fall back.

The exact versioned contract and examples live in `TUTOR_AGENT.md`.

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

The implemented response contains:

```text
interaction_id and request_id
status and confidence
canvas_actions (maximum 12)
grounding_references and warnings
course_boundary decision
learning_events and learning_delivery
```

`canvas_actions` is a discriminated union of `text`, `math`, `arrow`,
`circle`, `underline`, `highlight`, `check`, and `cross`. Each action validates
only the fields appropriate to its type. Text and math use a normalized
position, arrows use normalized start/end points, and target actions use a
normalized bounding box.

Gemini output is constrained by a schema and then validated independently with
Pydantic. The backend applies an additional deterministic policy for uncertain
analysis, course boundaries, and client-supported actions. The renderer never
receives arbitrary tldraw operations.

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

`canvas.image_width` and `canvas.image_height` are the encoded image's positive
integer pixel dimensions. For PNG exports, the frontend reads these values from
the IHDR header; tldraw's logical export width/height can be fractional and are
not valid substitutes. The world-space export bounds remain separate and are
used only by the renderer to map normalized actions back to tldraw coordinates.

## 19. Annotation Renderer
Frontend owns:
```text
TutorAnnotation
      ↓
Annotation Renderer
      ↓
tldraw operations
```
The renderer creates controlled text, math, arrows, highlights, circles, etc.
This boundary also enables future handwriting animation without changing tutor reasoning.

## 20. Canvas Capture
Expose a clean frontend boundary conceptually like:
```ts
async function captureCanvasForAnalysis(): Promise<Blob>
```
Hide low-level tldraw export details from unrelated code.
Where useful, send image plus structured metadata.

The capture boundary returns both the PNG's header-derived integer pixel
dimensions and the exact world-space bounds used for export. Client validation
rejects malformed dimensions before starting a multipart request.

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
index
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
Keep retrieval simple initially.
It must support tutoring, question generation, coverage checks, and style inference.
Semantic retrieval plus metadata filtering may be enough.
Evaluate by user-facing quality, not architectural sophistication.

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
Conceptual response:
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
  "latex_blocks": [],
  "figures": [],
  "metadata": {}
}
```
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

Tutor analysis now returns versioned learning events with topic, skill,
strength/mistake/progress/help-usage type, outcome, evidence, optional mistake
tag, confidence, tutor mode, difficulty, and request/session identifiers. When
`LEARNING_METRICS_WEBHOOK_URL` is configured, the backend posts these events in
the background. Delivery is best effort and non-blocking; the response copy is
the fallback until the learning engine provides durable ingestion.

Ren's learning engine separately persists explicit completed attempts in
SQLite and derives course-scoped skill mastery and next-problem specifications.
Tutor interactions are observational: Mark, Hint, Explain, and Stuck never
silently create an attempt or change mastery. Before each tutor workflow, the
backend adapts durable skill state into the existing `StudentModelSnapshot` so
the agents receive attempted topics, recurring misconceptions, established
strengths, and historical hint usage.

Completed attempts track `hints_used` and `stuck_requests` separately. Any
Stuck use applies the stronger multi-hint assistance score; it is not treated
as unassisted success. Existing SQLite databases receive the additive
`stuck_requests` column during startup. The default database is
`backend/mentora.db` and can be overridden with `MENTORA_DB_PATH`.

## 34. Built-In Course
Support at least one built-in demo course, likely Calculus I.
Where practical, seed it through the same Course Context mechanisms as uploaded courses to avoid a separate architecture.

The `calc1` seed taxonomy is also the bounded retrieval fallback for tutor
requests whose Pinecone lookup succeeds with no excerpts. It is not a generic
replacement for Course Context: only taxonomy-compatible expected skills and
their direct prerequisites are included, and no fallback occurs during a
provider outage.

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

The tutor implementation uses a Google ADK graph:

```text
Canvas Analyst (Gemini multimodal + CanvasAnalysis schema)
        ↓ validated ADK state handoff
Tutor Planner (Gemini + TutorPlan schema)
        ↓ independent Pydantic validation and safety policy
TutorResponse
```

ADK performs up to three bounded transient HTTP attempts. The application makes
one additional full workflow attempt only when structured output is malformed.
The model defaults to `gemini-3.7-flash` and is replaceable through
`GEMINI_MODEL`.

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

Tutor readiness requires `GEMINI_API_KEY`, `OPENAI_API_KEY`,
`PINECONE_API_KEY`, and `PINECONE_INDEX_NAME`. `/health` and tutor configuration
errors report missing variable names only. Image type is verified from file
signatures rather than trusting multipart headers. Optional learning webhooks
may be signed with HMAC-SHA256 through `LEARNING_METRICS_WEBHOOK_SECRET`.
Learning-engine state uses local SQLite and never requires provider secrets.

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
