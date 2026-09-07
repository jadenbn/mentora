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
│ Vertical whiteboard                   │
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
the frontend code. Its metadata and problem association are stored on the
server (`courses` and `spaces` tables in `backend/app/database.py`); the
canvas and tutor checkpoints remain in browser localStorage for now. A
generated problem is rendered in a pinned, typeset card above the infinite
canvas; its canonical grounding record lives in SQLite. Older locked problem
notes are removed on restore only when they match that space's current
structured problem.
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
Preserve student strokes, remaining system/imported shapes, AI shapes,
positions, styles, and useful metadata. The generated problem is canonical on
the space record rather than duplicated inside the tldraw snapshot.
Camera/viewport state may also be stored.
Avoid inventing a parallel graphics document model unless necessary.

The current student-facing surface is a page-like vertical document implemented
with one locked, system-owned transparent boundary shape in the tldraw document.
The frontend renders the white dotted page against a neutral workspace and
keeps the tldraw camera freely pannable and zoomable around it. The writing
surface starts at a readable minimum height and grows downward in chunks when
student content approaches its bottom safety margin. This is intentionally not
multi-page navigation yet; the persisted tldraw document remains the source of
truth.

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
The frontend's authoritative constants live in `lib/canvas/ownership.ts`.
Shapes the tutor draws carry `owner: "ai"` and the `interaction_id` that
produced them. Each response is also stored as a per-Space tutor checkpoint in
browser storage, including a document-only tldraw snapshot captured when the
request began; the selected checkpoint restores that canvas state without
moving the current viewport and renders its feedback.
History viewing is read-only and does not overwrite the live session. Ownership
no longer crosses the wire as a shape list: capture excludes tutor-authored
shapes from the image and sends their bounds as `prior_annotations`.
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
- microphone lifecycle, audio encoding, and transcript confirmation for voice
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
POST /api/voice/transcribe                    implemented
POST /api/courses/{course_id}/documents       implemented
GET  /api/courses/{course_id}/documents       implemented
POST /api/courses/{course_id}/questions/generate implemented
POST /api/courses/{course_id}/work            implemented
GET  /api/courses/{course_id}/skills-overview implemented
GET  /api/courses/{course_id}/search          implemented
GET  /api/courses                                implemented
POST /api/courses                                implemented
GET  /api/courses/{course_id}                   implemented
PATCH /api/courses/{course_id}                  implemented
DELETE /api/courses/{course_id}                 implemented
GET  /api/courses/{course_id}/spaces            implemented
POST /api/courses/{course_id}/spaces            implemented
PATCH /api/courses/{course_id}/spaces/{space_id} implemented
DELETE /api/courses/{course_id}/spaces/{space_id} implemented
GET  /api/spaces/{space_id}                     implemented
GET  /api/courses/{course_id}/sessions
POST /api/courses/{course_id}/sessions
GET  /api/sessions/{session_id}
PUT  /api/sessions/{session_id}
POST /api/problems/import
GET  /api/courses/{course_id}/student-model
```

The implemented course routes support course CRUD, document upload/listing,
grounded question generation, and Space CRUD. Space metadata lives on the
server; the canvas document and tutor checkpoints remain in browser
localStorage for now. The engine's own routes (`/work`, `/skills-overview`,
and the `/dev/*` surface) are documented separately in `LEARNING_ENGINE.md`.
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
canvas_image       optional PNG/JPEG/WebP; maximum 10 MB when present
prior_annotations  JSON array of normalized bounds; defaults to []
problem_context    optional validated ProblemContext JSON
transcript         optional spoken instruction; trimmed, max 1000 chars
```

Six fields at most, no JSON request body. Normal work-analysis requests send
an image, three scalars, and optionally the exact structured problem separately
from the image. The backend loads recorded document excerpts by problem id, so
course material never crosses the browser tutor boundary. A `stuck` request
with `problem_context` may omit the image; the tutor then reasons from the
structured question and course grounding alone.

Tutor-authored shapes are excluded from the exported image and their positions
are sent as `prior_annotations` instead, so the model cannot read its own
handwriting back as student work.

`transcript` is what the student asked out loud, and is optional in the strict
sense: omitting it leaves the request byte-for-byte what it was before voice
existed. See `TUTOR_AGENT.md`.

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

The frontend stores the last 10 validated responses per Space as tutor
checkpoints in local storage. Each checkpoint includes the document snapshot at
request time, while AI shapes remain renderable separately and user highlights
remain part of the document. The navbar exposes
immediate previous/next navigation and a visibility toggle; historical
navigation restores the checkpoint read-only, and the newest response always
selects the live canvas.

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
The implementation captures student work plus relevant prior tutor marks,
adds a bounded padding margin, and excludes system/problem shapes from the
image. The returned world-space frame is the same frame used to normalize
tutor coordinates and render them back onto tldraw. Development builds log a
temporary object URL for the exact outgoing image; the image is not persisted.
When `TUTOR_DEBUG_LOG_REQUESTS=1`, the backend also logs the assembled Gemini
request as structured JSON, including prompts, context, image metadata, and
generation config. Raw image bytes are intentionally omitted.

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
  ↓
synchronous OpenAI embedding + Pinecone upsert
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

SQLite is the source of truth for document metadata and exact chunk text.
Pinecone stores `text-embedding-3-small` vectors with `course_id`, `document_id`,
and `chunk_id` metadata, but never chunk text. Small documents send full
context; larger ones retrieve semantically — filtered by both course and
selected document, ranking chunk ids in Pinecone and hydrating their exact
text from SQLite. Generated problems still record the one to eight chunks the
model actually used, so later tutor interactions reuse exact grounding without
another semantic search.

The Pinecone index is provisioned outside the application with 1,536 dimensions
and cosine similarity. Upload indexing and semantic search both run in worker
threads so FastAPI's event loop stays free; re-uploading a content-addressed
document is the repair path after a provider failure.

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
Implemented input is a course id, one document id, and a required 1–1,000
character question request describing topic, style, format, or difficulty.
Documents whose serialized context is at most 40,000 characters (configurable
with `QUESTION_FULL_CONTEXT_MAX_CHARS`) send every SQLite chunk to Gemini.
Larger documents use the request to retrieve 12 Pinecone-ranked chunk ids and
hydrate their text from SQLite. Structured provider output supplies the visible
prompt plus validated source chunk ids. Generated prompts use plain text with
`$...$` inline and `$$...$$` display LaTeX so the pinned problem card can render
readable mathematical notation without accepting arbitrary HTML. Request:
```json
{
  "document_id": "doc_123",
  "question_request": "Create a difficult conceptual chain-rule question"
}
```
Current endpoint: `POST /api/courses/{course_id}/questions/generate` accepts a
document ID and an optional question request — blank lets the learning engine
pick the topic and difficulty (see `LEARNING_ENGINE.md`). The direct
`google-genai` workflow returns a validated plan, checks grounding IDs against
retrieved chunks, identifies the skill(s) the question exercises, and persists
the generated problem, its grounding, and its skill attribution in SQLite.

Response:
```json
{
  "problem": {
    "id": "problem_123",
    "course_id": "course_demo",
    "document_id": "doc_123",
    "source": "generated",
    "prompt": "Evaluate ...",
    "created_at": "..."
  },
  "skills": [
    {"id": "calc1.chain-rule", "name": "Chain rule", "difficulty_band": 0.5}
  ]
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
Imported-problem reconstruction is not built. Generated problems already use a
structured record, rendered directly on the canvas as locked system-owned
tldraw shapes using KaTeX, with a readable fallback for malformed LaTeX.
Capture excludes system shapes from the analysis image while `problem_context`
preserves the complete question for Gemini; an eventual imported problem must
join that same boundary rather than making the tutor infer it from student
pixels.
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
Space canvas documents and tutor checkpoints use browser localStorage for now;
course metadata, Space metadata, course documents, chunks, generated problems,
and grounding use SQLite. Pinecone is an index, never the canonical text store.

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
Implemented as an extra input to the existing tutor call, not a second
assistant:
```text
microphone (MediaRecorder)
  ↓
re-encode to 16 kHz mono WAV in the browser
  ↓
POST /api/voice/transcribe   →  Gemini  →  transcript
  ↓
the student reads it, edits it, and taps Ask   ← nothing is sent before this
  ↓
POST /api/tutor/analyze with transcript + canvas + problem + course
  ↓
the same validated canvas actions, drawn by the same renderer
```

A transcript is never submitted to the tutor on arrival. Speech recognition is
wrong often enough that spending a tutor call on a misheard question costs more
than one extra tap, and the student is the only one who knows what they meant.
Rerecord and Cancel leave from the same step. Which tutor mode the confirmed
question uses is unchanged: `explain` when there is written work to look at,
`stuck` when there is not.

Transcription is deliberately a separate round trip rather than audio attached
to the tutor call. It keeps the tutor at one model call, lets the interface
show transcribing and thinking as the distinct waits they are, and confines the
audio to the request that carried it — nothing is persisted and no object URL
is ever created.

The browser re-encodes because MediaRecorder's container is browser-dependent
(Safari: AAC in MP4, Chrome: Opus in WebM) and the provider documents neither.
One format crossing the wire means one signature to verify server-side. The
sample rate is enforced in the encoder rather than taken on trust, which is
what keeps the longest allowed recording inside the server's 5 MiB cap.

`getUserMedia` requires a secure context, so voice works on `localhost` and
over HTTPS but not on a plain-HTTP LAN address — which is how an iPad is
usually reached in development. See the README.

Frontend layout, deliberately outside `Whiteboard.tsx`:
```text
lib/voice/microphone.ts     MediaStream + MediaRecorder, guaranteed teardown
lib/voice/wav.ts            decode and re-encode
lib/voice/voiceCapture.ts   the lifecycle state machine, framework-free
lib/voice/useVoiceCapture.ts  React binding
features/tutor/TutorControls.tsx  the microphone, on the tutor action fan
features/tutor/VoiceControl.tsx   recording and confirmation, presentation only
features/tutor/StatusPill.tsx     the shared "we are waiting" indicator
```
The lifecycle is one discriminated union rather than a set of flags:
`idle | requesting | recording | stopping | transcribing | confirming |
submitting`, each carrying only the data that step owns — an elapsed clock
exists exactly while the microphone is open, a transcript exactly while there
is one to review or send.

Starting a spoken question is a tutor action, so the microphone fans out of the
same right-edge control as Mark, Hint, Explain, and I'm Stuck rather than
occupying its own corner. While a question is being recorded, transcribed,
reviewed, or sent, the other tutor actions are disabled: they share one busy
slot, and a button tapped mid-question would drop the words already spoken.
`StatusPill` exists so that "Thinking" and "Transcribing" are the same object
rather than two indicators that resemble each other, and only one of them is
ever on screen — the tutor call is announced once, by the whiteboard.

The provider lives behind `app/agents/transcription_workflow.py`, the one
module voice may import an SDK into; replacing the speech-to-text service means
replacing that file. It reuses `GEMINI_API_KEY`, so voice adds no credential
and no dependency. It calls a dedicated speech-to-text model
(`gemini-3.5-transcribe`) through the Interactions API: the WAV is uploaded,
transcribed, and deleted again within the request. That model takes no prompt,
no response schema, and no thinking configuration, so the adapter sends none —
see `TUTOR_AGENT.md`.

Transcripts are untrusted twice: speech the tutor did not choose, and
provider-generated text. They are trimmed, capped, and delimited before they
reach a prompt, which states that nothing inside them changes the rules. The
confirmation step adds a third check that no provider can bypass: a person read
the words before they were sent.

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

The tutor observes plenty worth recording, but the learning engine wants
closed-vocabulary, slug-identified, float-typed facts and the tutor produces
prose. That adapter now exists: `app/services/attempt_grading.py` turns a
graded `WorkStatus` (correct / incorrect / partial / uncertain) into the
per-skill `AttemptGrading` that `record_attempt` ingests. See §47 for the
full closed loop and its remaining granularity gap.

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

The tutor is one direct asynchronous Gemini call through the `google-genai` SDK:

```text
student-only canvas image + mode + problem + recorded excerpts
                         + prior annotation bounds
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
structured output is malformed. The same direct boundary powers grounded
question generation. The model defaults to `gemini-3.5-flash-lite` and is
replaceable through `GEMINI_MODEL`; thinking defaults to `low` and is
replaceable through `GEMINI_THINKING_LEVEL`. These settings are shared by
tutoring and grounded question generation.

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

Tutor and question-generation readiness — and voice with it — require
`GEMINI_API_KEY` and nothing else. Course indexing and large-document
retrieval additionally require `OPENAI_API_KEY`, `PINECONE_API_KEY`, and
`PINECONE_INDEX_NAME`. `/health` reports these readiness groups separately
and configuration errors expose missing variable names only. Image and audio
types are verified from file signatures rather than trusting multipart
headers. Recorded audio is never written to disk or persisted.

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

## 47. Integrated Learning Engine

The backend is the merge of two halves: the **tutor product** (Gemini
whiteboard tutor, grounded question generation, Pinecone retrieval, document
repository, course and space CRUD — everything above) and the **learning
engine**, which has no surface of its own. It is the tutor's brain: a
per-course topic list and a per-student read of how they're doing on each
one, consulted implicitly during question generation. There is no
student-facing "next problem" screen and no mastery score shown anywhere —
see `docs/LEARNING_ENGINE.md` for the full design, this section is only how
the two halves connect.

### 47.1 Two persistence layers, one file

Two ORMs open the same `backend/mentora.db`:

```text
app/db.py        SQLModel engine   -> skill, skill_state, attempt,
                                       hint_usage, problem_skill
app/database.py  raw sqlite3       -> courses, spaces, course_documents,
                 CourseRepository     document_chunks, generated_problems,
                                       problem_grounding_chunks,
                                       problem_difficulty
```

`courses` and `spaces` are DB-owned, not engine tables: `courses` is the
single source of truth for which course ids exist, seeded with two demo rows
(`course_demo`, `course_linear`) and otherwise grown by `POST /api/courses`,
which mints `course_{uuid4().hex}` ids. The engine's tables carry `course_id`
as a plain string with no foreign key back to `courses` -- the two ORMs never
join across the file -- so every engine route that takes a `course_id`
validates it against `courses` at the boundary (`api.dependencies.
require_course`) before touching a skill or an attempt. See 47.4 for what a
freshly created course's topic list looks like.

`ProblemSkill` -- which skill(s) a generated problem counts toward -- lives in
the SQLModel layer specifically so `skill_id` can carry a real foreign key to
`skill.id`; that guarantee is worth a dedicated table and is why this table
moved out of the raw layer. Documents, chunks, and generated problems stay
raw: content-addressed blob storage, not something either the topic list or
attempts logic ever join against directly.

Two rules keep the split safe:

- **One source of truth for the path.** Both resolve `MENTORA_DB_PATH` through
  `app.config.database_path()`.
- **Survive two writers.** Each layer enables `PRAGMA journal_mode=WAL` and
  `PRAGMA busy_timeout=5000`; the SQLModel engine also enables
  `PRAGMA foreign_keys=ON` (off by default in SQLite, which would make
  `ProblemSkill`'s FK a comment rather than a constraint).

### 47.2 The loop

There is one generation route, `POST /api/courses/{course_id}/questions/generate`,
and the engine is consulted inside it rather than through a route of its own:

```text
student types a request, or leaves it blank
        |
        +-- blank -> selection.pick_topic()   picks a topic + difficulty from
        |                                       this student's per-topic accuracy
        +-- typed -> profile.get_profile()    contributes a difficulty level
        |                                       from overall accuracy; the
        |                                       student's own topic wins
        v
QuestionService.generate()      a grounded problem; the model also names the
                                  skill(s) it thinks the question exercises
        |
        +-- names an existing topic  -> attributed to it
        +-- names something new      -> inserted as a new topic (the
        |                                piggyback)
        v
attribution.set_problem_skills() + repository.set_problem_difficulty()
        |
        v
POST /work        the student's canvas; the tutor grades it server-side and
                    record_attempt() updates the topic's rolling accuracy window
```

**The client never scores its own work.** `POST /work` replaced an earlier
`POST /attempts` that took `correct` straight from the browser; the tutor's own
reading of the canvas decides the outcome now, and difficulty is read back from
`problem_difficulty` rather than restated by the client. `POST
/dev/courses/{id}/attempts` still takes a stated outcome, and its docstring
says why that is fine there and nowhere else: it drives the dashboard without a
canvas or a model call.

### 47.3 Topics are flat, and can only grow through the piggyback

There is no prerequisite graph and no unlock gate. An earlier gated design
(mastery estimate + a fixed unlock threshold) starved a real demo course — an
average student's estimate correctly settled at their true ability, which sat
below the gate, so they never reached most of the material. A flat pool scored
by weakness and staleness (`services/selection.py`) doesn't have that failure
mode.

**A topic can only be added by `QuestionService._attribute_skills`.** Every
question the model generates also names the topic(s) it exercises. Each name
resolves three ways, in order: an exact normalized-id match; a
name-similarity match (`taxonomy.canonical_key` — same significant words,
any order, case, or article, so "the chain rule" and "chain rule" collapse to
one topic without an embedding call); or, if neither matches, a genuinely new
topic. New topics go through `build_taxonomy` — the same normalizer and
validator every topic source uses — and then `taxonomy.add_skills`, which
inserts it. The database is the sole source of truth; there is no seed file
anywhere, so a freshly created course starts with zero topics and grows
entirely through this path (see 47.4). The one other writer is
`POST /dev/courses/{id}/skills/import`, which runs a pasted batch through the
same `build_taxonomy` → `add_skills` call — useful for testing a topic list
without a model call, but otherwise equivalent to the piggyback.

A malformed batch (e.g. two entries that collide after normalization) raises
`TaxonomyError` inside `_attribute_skills`; it is caught and logged there, and
the student still gets their problem, attributed only to whatever topic
selection required.

### 47.4 Cold start

A brand-new course has no topics and nothing to select. `pick_topic` returns
`None` in that case, and the route falls back to "write a question grounded
in this material" with no required topic — the model's own read of the
document seeds the first one or two topics through the ordinary piggyback
path. Every generation after that has topics to select from. There is no
separate bootstrap call, and this applies uniformly to every course:
`course_demo` and `course_linear` (the two rows `CourseRepository` seeds) cold
start exactly like a course a user just created through `POST /api/courses`.

One visible cost of that uniformity: `normalize_slug` prefixes every skill id
with its course id, so a topic on a UUID-named course reads as
`course_a1b2c3....chain-rule` rather than something short like
`calc1.chain-rule`. Functional, and never surfaced to a student, but worth
knowing when reading the dev dashboard or `/dev` responses.

### 47.5 What was cut, and why

An earlier version of this engine was a small adaptive-learning platform: an
Elo/IRT mastery estimator with read-time decay and a confidence function, a
skill DAG with unlock gating and prerequisite bleed, a forced-review floor, a
dedicated LLM taxonomy-generation path, and a proposal-and-review queue for
new skills (observation counts, embedding-based deduplication, a promotion
step). All of it is gone. Two reasons converged:

- **It had a user interface, and it should not have one.** A "practice next
  skill" button and a mastery readout on the whiteboard made the engine a
  feature the student interacted with, when it should be invisible
  infrastructure the tutor consults.
- **It was over-built for what the product actually asks for.** `PRODUCT.md`
  §23 asks the MVP to track attempts, correct/incorrect, hints used, and
  difficulty — counters, not a fitted ability model — and §24 explicitly
  prefers qualitative insight over "one opaque mastery score."

What replaced it: a rolling window of recent outcomes per topic
(`services/accuracy.py`), a flat priority formula with no gate
(`services/selection.py`), and a student profile derived on read from the
attempt ledger rather than stored (`services/profile.py`). `GET
.../skills-overview` (dev dashboard only) now shows `accuracy`/`attempts`
instead of `mastery`/`confidence`/`unlocked`.
