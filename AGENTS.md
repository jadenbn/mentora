# AGENTS.md

This repository is developed by a six-person hackathon team using both human contributors and agentic coding tools. Agents should optimize for **speed, clarity, safe integration, and minimal merge conflicts**.

The product is an AI-powered tutoring whiteboard. Students work through problems on a digital canvas, while an AI tutor can inspect their work, provide hints, mark mistakes, and write annotations directly onto the whiteboard. Course-specific context can come from uploaded course materials or built-in subject content.

---

# 1. Non-Negotiable Git Rules

## Branch naming

**Every branch MUST be prefixed with the human developer's name followed by `/`.**

Examples:

```text
jaden/tldraw-canvas
jaden/fix-annotation-positioning
lana/course-upload
marco/vision-endpoint
```

Never create branches such as:

```text
feature/tldraw
fix/backend
ai-agent-work
annotations
```

The required format is:

```text
[name]/[short-description]
```

Before creating a branch, determine which human developer the agent is acting on behalf of.

If the developer's name is not known, **do not invent one**. Ask the developer before creating a branch.

Branch names should:

* use lowercase
* use hyphens between words
* be short but descriptive
* describe one logical unit of work

Example:

```bash
git checkout -b jaden/canvas-export
```

## Never work directly on `main`

Agents MUST NOT:

* commit directly to `main`
* force-push `main`
* rewrite `main` history
* merge their own branch into `main` unless explicitly instructed
* delete another developer's branch

Work should happen on a correctly prefixed feature branch.

---

# 2. Repository Philosophy

This is a hackathon project.

Optimize for:

1. A working end-to-end demo
2. Simple interfaces between components
3. Fast iteration
4. Reliability
5. Readable code
6. Easy integration

Do **not** optimize prematurely for:

* large-scale distributed architecture
* elaborate abstractions
* microservices
* enterprise authentication
* perfect database normalization
* complex design patterns
* speculative future requirements

Prefer the simplest implementation that cleanly supports the demo.

---

# 3. Product Overview

The intended user flow is approximately:

```text
Student opens course
        ↓
Selects topic / practice mode
        ↓
AI generates a problem
        ↓
Problem appears on tldraw canvas
        ↓
Student solves it by hand
        ↓
Student requests:
  - Check my work
  - Hint
  - Nudge
  - Explain
  - I'm stuck
        ↓
Canvas is analyzed by AI
        ↓
Backend returns structured tutor feedback
        ↓
Frontend renders AI annotations on canvas
        ↓
Student continues solving
        ↓
Attempt/progress may be recorded
```

A second flow allows course-specific material:

```text
Student uploads course material
        ↓
Backend extracts/indexes content
        ↓
Relevant context is retrieved
        ↓
Tutor generates course-aligned questions
```

The central product experience is:

> The AI tutor sees the student's work and teaches directly on the whiteboard.

Agents should preserve that experience when making architectural decisions.

---

# 4. Technology Stack

## Frontend

Primary frontend stack:

```text
TypeScript
React
Next.js
tldraw
```

The application should be designed primarily as a responsive web application, with particular attention to:

* desktop browsers
* iPad Safari
* touch input
* stylus input where supported
* landscape tablet layouts

We are **not** using React Native as the primary hackathon frontend.

The whiteboard should use **tldraw**, rather than implementing a drawing engine from scratch.

### Frontend responsibilities

The frontend owns:

* application UI
* whiteboard interaction
* tldraw editor state
* drawing
* erasing
* selection
* undo/redo
* displaying generated problems
* rendering tutor annotations
* collecting user actions
* requesting tutor feedback
* course selection/upload UI
* loading/error states

---

# 5. Backend

Backend stack:

```text
Python
FastAPI
Pydantic
```

Prefer modern Python with type hints.

Recommended baseline:

```text
Python 3.12+
FastAPI
Pydantic v2
uvicorn
```

The backend is responsible for:

* AI API calls
* multimodal analysis
* tutor logic
* question generation
* document processing
* course retrieval/RAG
* student/session state
* structured annotation responses
* protecting API keys and secrets

The frontend should never directly contain private AI provider API keys.

---

# 6. Suggested Repository Structure

Prefer a simple monorepo.

Example:

```text
/
├── AGENTS.md
├── README.md
├── frontend/
│   ├── app/
│   ├── components/
│   ├── features/
│   ├── lib/
│   ├── types/
│   ├── public/
│   ├── package.json
│   └── tsconfig.json
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── prompts/
│   │   └── utils/
│   ├── tests/
│   ├── pyproject.toml
│   └── .env.example
│
└── docs/
```

Do not reorganize the entire repository without explicit approval.

When adding functionality, prefer extending the existing structure instead of creating a competing architecture.

---

# 7. Frontend Conventions

## TypeScript

Use TypeScript for all new frontend code.

Avoid:

```ts
any
```

unless there is a clear reason.

Prefer explicit shared interfaces for API boundaries.

Example:

```ts
export interface TutorAnnotation {
  id: string;
  type: "text" | "arrow" | "circle" | "highlight" | "check" | "cross";
  x: number;
  y: number;
  width?: number;
  height?: number;
  text?: string;
}

export interface TutorResponse {
  status: "correct" | "incorrect" | "partial" | "needs_clarification";
  message?: string;
  annotations: TutorAnnotation[];
}
```

If a backend schema exists for the same data, keep the two representations synchronized.

---

# 8. React Rules

Prefer:

* functional components
* hooks
* small reusable components
* colocating feature-specific logic
* clear state ownership

Avoid unnecessary global state.

Use local state unless multiple unrelated components truly need shared access.

Do not introduce a new state management library without a demonstrated need.

For server communication, keep API access behind a small client layer rather than scattering raw `fetch()` calls throughout components.

Example:

```text
frontend/lib/api/
    tutor.ts
    courses.ts
    questions.ts
```

---

# 9. tldraw Rules

tldraw is the source of truth for the interactive whiteboard.

Do not build a second canvas implementation alongside it unless explicitly approved.

Keep AI-generated objects distinguishable from user-generated objects.

For example, attach metadata such as:

```ts
{
  source: "ai"
}
```

where practical.

Possible AI annotations include:

* text
* arrows
* circles
* highlights
* checkmarks
* crosses
* underlines

Do not allow the LLM to directly execute arbitrary tldraw operations.

Instead:

```text
LLM
 ↓
validated structured annotation JSON
 ↓
frontend annotation adapter
 ↓
tldraw editor API
```

This boundary is important.

---

# 10. Coordinate System for AI Annotations

AI systems may analyze an exported image of the canvas.

Use normalized coordinates at API boundaries whenever possible:

```text
x ∈ [0, 1]
y ∈ [0, 1]
```

For example:

```json
{
  "type": "circle",
  "x": 0.53,
  "y": 0.61,
  "width": 0.08,
  "height": 0.05
}
```

The frontend should convert normalized coordinates into actual canvas coordinates.

Avoid making AI prompts dependent on device-specific pixel sizes.

This helps keep behavior consistent between:

* desktop
* laptop
* iPad
* resized browser windows

---

# 11. AI Tutor Architecture

The tutor should produce structured data, not arbitrary UI instructions.

Conceptually:

```text
Canvas state/image
        +
Course context
        +
Problem
        +
Tutor mode
        ↓
Multimodal model
        ↓
Validated response
        ↓
TutorResponse
        ↓
Frontend renderer
```

Tutor modes may include:

```text
check
hint
nudge
explain
stuck
```

Expected behavioral differences:

### `check`

Evaluate current work.

Do not unnecessarily reveal future steps.

### `hint`

Give useful guidance without solving the problem.

### `nudge`

Give the smallest intervention possible.

Prefer identifying an area to reconsider.

### `explain`

Explain a detected misconception or error.

### `stuck`

Provide a more substantial next step, potentially writing part of the next step onto the canvas.

---

# 12. Structured AI Output

All AI outputs consumed programmatically should use validated structured schemas.

Do not parse free-form prose using brittle regex if structured output is available.

Example Pydantic model:

```python
from typing import Literal
from pydantic import BaseModel


class TutorAnnotation(BaseModel):
    type: Literal[
        "text",
        "arrow",
        "circle",
        "highlight",
        "check",
        "cross",
    ]

    x: float
    y: float

    width: float | None = None
    height: float | None = None
    text: str | None = None


class TutorResponse(BaseModel):
    status: Literal[
        "correct",
        "incorrect",
        "partial",
        "needs_clarification",
    ]

    message: str | None = None
    annotations: list[TutorAnnotation]
```

Validate model responses before sending them to the frontend.

Gracefully handle invalid AI output.

---

# 13. Vision / Handwriting Strategy

Do not assume traditional OCR is required.

For the MVP, the expected approach is:

```text
tldraw canvas
      ↓
export snapshot/image
      ↓
multimodal model
      ↓
interpret handwritten work
```

Traditional OCR may later be introduced if it demonstrably improves performance.

Agents should not add OCR infrastructure merely because handwritten text exists.

First validate whether the multimodal model is sufficient.

---

# 14. Canvas Export

The frontend should expose a clean way to capture the relevant work for AI analysis.

Prefer an interface conceptually similar to:

```ts
export async function captureCanvasForAnalysis(): Promise<Blob>
```

The rest of the frontend should not need to know how tldraw performs the export.

If feasible, send additional metadata alongside the rendered image, such as:

* viewport bounds
* problem text
* canvas dimensions
* relevant shape metadata
* AI annotation IDs
* student shape IDs

This may improve model reasoning.

---

# 15. Course Context / RAG

Course materials may include:

* lecture slides
* handwritten or typed notes
* assignments
* practice exams
* syllabi
* formula sheets

The RAG pipeline should remain simple for the hackathon.

Conceptually:

```text
upload
  ↓
extract text
  ↓
chunk
  ↓
embed/index
  ↓
retrieve relevant chunks
  ↓
pass to tutor/question generator
```

Avoid building an elaborate retrieval system prematurely.

The goal is:

> Make generated questions and explanations align with what the student's course actually teaches.

Prefer storing source metadata with each chunk:

```python
{
    "course_id": "...",
    "document_id": "...",
    "filename": "...",
    "page": 12,
    "text": "..."
}
```

---

# 16. Built-In Courses

The application should not require document uploads to be demoable.

Support at least one built-in course or subject.

Good initial candidates:

```text
Calculus I
```

Optionally:

```text
Linear Algebra
Physics I
Intro Programming
```

A judge should be able to open the application and immediately start a tutoring session.

---

# 17. Question Generation

Question generation should return structured objects.

Example:

```json
{
  "id": "question-123",
  "topic": "integration-by-parts",
  "difficulty": "medium",
  "prompt": "Evaluate ∫ x e^x dx.",
  "expected_skills": [
    "integration-by-parts"
  ]
}
```

Do not tightly couple generated questions to one UI representation.

The whiteboard renderer decides how the question appears.

---

# 18. Learning / Mastery System

Keep mastery tracking lightweight for the MVP.

Example:

```json
{
  "integration_by_parts": {
    "mastery": 0.72,
    "attempts": 8
  },
  "u_substitution": {
    "mastery": 0.91,
    "attempts": 14
  }
}
```

Do not build a sophisticated psychometric model during the hackathon unless the core tutor is already working reliably.

A simple heuristic is acceptable.

For example:

```text
correct unassisted:
    mastery increases significantly

correct after hint:
    mastery increases slightly

incorrect:
    mastery decreases slightly
```

The important product behavior is that the next problem can plausibly adapt to student performance.

---

# 19. Backend API Design

Prefer straightforward REST endpoints.

Possible API:

```text
GET  /health

POST /api/courses
POST /api/courses/{course_id}/documents

POST /api/questions/generate

POST /api/tutor/analyze
POST /api/tutor/hint

GET  /api/students/{student_id}/mastery
POST /api/attempts
```

Do not create separate endpoints merely because individual model prompts differ if they logically represent the same operation.

Example request:

```json
{
  "question_id": "q123",
  "mode": "hint",
  "canvas_image": "...",
  "course_id": "course123"
}
```

---

# 20. FastAPI Conventions

Keep route handlers thin.

Bad:

```python
@app.post("/api/tutor/analyze")
async def analyze(...):
    # 200 lines of model logic
```

Preferred:

```python
@router.post("/analyze", response_model=TutorResponse)
async def analyze_tutor_request(
    request: TutorRequest,
) -> TutorResponse:
    return await tutor_service.analyze(request)
```

Place business logic in services.

Example:

```text
backend/app/services/
    tutor_service.py
    question_service.py
    course_service.py
    document_service.py
```

---

# 21. Python Style

Use:

* type hints
* `async` where appropriate
* Pydantic models
* small functions
* descriptive names

Prefer:

```python
async def generate_question(
    request: GenerateQuestionRequest,
) -> GeneratedQuestion:
```

over:

```python
async def do_stuff(data):
```

Avoid deeply nested code.

Prefer early returns.

---

# 22. Error Handling

The application must fail gracefully.

Frontend users should never see raw:

* Python exceptions
* stack traces
* AI SDK errors
* JSON parsing errors

Backend should return appropriate HTTP errors.

Example:

```json
{
  "detail": "Unable to analyze the current canvas."
}
```

Log the underlying technical error on the server.

---

# 23. AI Failure Handling

AI calls will occasionally fail.

Code defensively.

Handle:

* timeout
* rate limits
* malformed structured output
* empty responses
* image upload failures
* model refusal
* network errors

Do not let one bad AI call crash the session.

Where appropriate, allow retry.

---

# 24. Environment Variables

Secrets belong in environment variables.

Never commit:

```text
API keys
tokens
database passwords
private URLs
credentials
```

Provide:

```text
.env.example
```

Example:

```text
OPENAI_API_KEY=
DATABASE_URL=
```

Never put real secret values in `.env.example`.

---

# 25. Dependency Rules

Before installing a dependency, ask:

1. Does the project already have something that solves this?
2. Can this reasonably be implemented without another dependency?
3. Does this dependency materially accelerate hackathon development?

Avoid installing overlapping libraries.

For example, don't introduce multiple:

* HTTP clients
* state management frameworks
* validation systems
* canvas libraries
* UI component systems

without a strong reason.

---

# 26. Shared Interfaces

The most important integration boundaries are:

```text
Frontend ↔ Backend
Backend ↔ AI
Backend ↔ RAG
AI output ↔ tldraw annotations
```

Keep those contracts explicit.

If changing an API schema:

1. Search for every consumer.
2. Update both backend and frontend types.
3. Update tests.
4. Verify the complete request/response flow.

Do not silently change shared interfaces.

---

# 27. Agent Ownership and Coordination

Before editing code, identify the likely ownership area.

Core areas are:

```text
Frontend / Whiteboard
AI Tutor / Vision
Course Context / RAG
Backend / Infrastructure
Learning / Question Generation
Integration / Generalist
```

If work clearly belongs to another person's active area, avoid large overlapping changes unless necessary.

Prefer adding a clean interface that allows both contributors to work independently.

---

# 28. Minimize Merge Conflicts

This team will have six people and potentially multiple coding agents working simultaneously.

Agents MUST actively minimize merge conflicts.

Before modifying a central file, ask whether the change can live in a separate module.

Files likely to become conflict hotspots include:

```text
frontend/app/page.tsx
frontend/package.json
backend/app/main.py
README.md
```

Avoid placing all logic into these files.

For example, instead of continually editing:

```text
backend/app/main.py
```

create:

```text
backend/app/api/tutor.py
backend/app/api/courses.py
backend/app/api/questions.py
```

and register routers cleanly.

---

# 29. Scope Discipline

Agents should not opportunistically refactor unrelated code.

If asked:

> Add tutor annotations.

Do not also:

* rename unrelated folders
* replace the UI framework
* change database libraries
* rewrite course ingestion
* format the entire repository

Keep changes scoped.

This is especially important because many agents may be working simultaneously.

---

# 30. When Existing Code Looks Bad

Hackathon code may be imperfect.

Do not automatically rewrite it.

Before substantial refactoring, evaluate:

```text
Does this prevent the requested feature?
Does this create a serious bug?
Will this meaningfully reduce integration risk?
```

If not, leave it alone.

Working code has value.

---

# 31. Testing Expectations

Every meaningful backend feature should have at least lightweight tests where practical.

Especially test:

* Pydantic validation
* coordinate transformations
* annotation parsing
* question-generation schemas
* tutor response schemas
* deterministic helper functions

Do not overinvest in testing visual polish during the hackathon.

For the frontend, prioritize testing critical utilities and manually validating the main flow.

---

# 32. Critical End-to-End Test

The most important test in the repository is effectively:

```text
Open app
    ↓
Load problem
    ↓
Write on canvas
    ↓
Press Check
    ↓
Canvas is captured
    ↓
Backend receives image
    ↓
AI analyzes image
    ↓
Structured annotation returned
    ↓
Annotation appears in correct place
```

Whenever making changes to the canvas, tutor endpoint, AI schema, or annotation system, verify this path still works.

---

# 33. Demo Reliability Beats Architectural Purity

If choosing between:

```text
beautiful abstraction
```

and:

```text
reliable demo
```

prefer the reliable demo.

Examples:

It is acceptable to:

* preload a built-in Calculus I course
* seed a few known-good questions
* simplify mastery scoring
* support a limited annotation set
* manually choose a model suited for the demo

It is not acceptable to fake the central AI interaction while claiming it is live.

---

# 34. Logging

Backend logs should make integration debugging easy.

Useful log events include:

```text
request received
canvas image received
model request started
model request completed
structured response validated
annotation count
retrieval result count
error details
```

Do not log sensitive user content unnecessarily.

Do not log API keys.

---

# 35. Performance

The user should receive tutor feedback quickly enough that the application feels interactive.

Avoid sequential work when operations can safely run concurrently.

Do not optimize prematurely, but pay attention to obvious latency sources such as:

```text
very large images
unnecessarily huge prompts
retrieving excessive course context
multiple redundant AI calls
```

Resize/compress canvas snapshots if they are much larger than needed.

---

# 36. Prompt Management

Do not scatter large prompt strings throughout route handlers.

Store reusable prompts under something like:

```text
backend/app/prompts/
```

Example:

```text
tutor.py
question_generation.py
course_analysis.py
```

Prompts should clearly specify:

* role
* available context
* expected behavior
* tutor mode
* output schema
* constraints

---

# 37. Tutor Behavior Principles

The tutor should support learning rather than immediately giving answers.

Default behavior:

```text
smallest useful intervention first
```

Prefer:

> Check what happens to the sign in this step.

over:

> The answer is xe^x - e^x + C.

Unless the student explicitly requests a full explanation or answer.

The tutor should respond to the selected mode.

---

# 38. AI Annotation Philosophy

Annotations should feel like something a human tutor might place on paper.

Prefer:

```text
circle mistake
arrow toward relevant expression
short handwritten-style note
check mark beside correct work
underline relevant portion
```

Avoid covering the canvas with paragraphs.

Long explanations belong in a separate tutor panel if needed.

Canvas feedback should be concise.

---

# 39. AI/User Shape Separation

Where practical, preserve the distinction between:

```text
student-created shapes
AI-created shapes
system/problem shapes
```

This enables future functionality such as:

```text
hide tutor annotations
undo tutor response
analyze only student work
clear AI feedback
```

Do not flatten everything into indistinguishable canvas elements if metadata is available.

---

# 40. Problem Text

Problem content should preferably be inserted into the canvas in a controlled area.

Avoid including problem text in the same region where students are expected to work.

The AI analyzing the screenshot should know:

* the original problem
* which shapes were generated by the system
* which shapes were written by the student

whenever possible.

---

# 41. Authentication

Authentication is **not a priority** unless specifically required by the hackathon.

Do not spend major development time building a complex login system before the tutoring loop works.

A temporary or local user/session model is acceptable.

---

# 42. Database

Use the simplest database/storage solution that satisfies actual requirements.

For a hackathon, lightweight persistence is acceptable.

Do not introduce complex database infrastructure before there is data worth persisting.

Likely entities:

```text
User
Course
Document
Question
Attempt
Mastery
Session
```

---

# 43. File Uploads

Validate uploaded files.

Do not trust:

* filename
* MIME type
* extension
* file size

Limit file sizes appropriately.

For the initial MVP, supporting PDF is sufficient unless another format is explicitly needed.

---

# 44. Security

Even though this is a hackathon:

Never:

* expose server API keys to browser code
* execute user-provided code
* concatenate untrusted input into shell commands
* commit credentials
* blindly trust model-produced instructions
* allow arbitrary model output to trigger backend operations

Treat model output as untrusted data and validate it.

---

# 45. API Compatibility

If an endpoint already exists, avoid breaking it unnecessarily.

When a breaking API change is required:

1. Update backend schema.
2. Update frontend types.
3. Update API client.
4. Update all call sites.
5. Verify the end-to-end flow.

Do this in the same branch whenever practical.

---

# 46. Code Comments

Comments should explain **why**, not narrate obvious syntax.

Good:

```python
# Normalize coordinates so annotations remain stable across
# different viewport sizes and tablet/desktop resolutions.
```

Bad:

```python
# Set x to annotation x
x = annotation.x
```

---

# 47. Documentation

When introducing a major new subsystem, update documentation enough that another teammate can use it.

Examples:

```text
new environment variable
new backend startup command
new endpoint
new required service
new database migration
```

Do not write extensive documentation for trivial internal helpers.

---

# 48. Local Development

The project should remain straightforward to run locally.

Target workflow:

Backend:

```bash
cd backend
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Prefer a small number of setup commands.

If setup changes, update the README.

---

# 49. Formatting and Linting

Follow existing project tooling.

Frontend commonly should support:

```text
eslint
prettier
TypeScript type checking
```

Backend commonly should support:

```text
ruff
pytest
```

Do not introduce competing formatters.

Before completing meaningful work, run the relevant available checks.

---

# 50. Agent Workflow

When an agent receives a coding task:

### Step 1 — Inspect

Understand:

* current architecture
* related files
* existing interfaces
* current branch

### Step 2 — Check branch

Ensure the branch follows:

```text
[name]/description
```

Never proceed with significant edits directly on `main`.

### Step 3 — Scope

Identify the smallest coherent implementation.

### Step 4 — Implement

Write clear, maintainable code that fits the existing architecture.

### Step 5 — Validate

Run relevant:

```text
tests
type checks
linting
build
```

### Step 6 — Review diff

Before finishing:

```bash
git diff
git status
```

Ensure no:

* accidental generated files
* secrets
* unrelated changes
* giant formatting diffs
* debug code

### Step 7 — Report

Tell the developer:

* what changed
* key files changed
* how to test it
* known limitations
* whether anything requires coordination with another teammate

---

# 51. Commits

Prefer focused commits.

Good:

```text
Add normalized tutor annotation schema
Render tutor circles on tldraw canvas
Add canvas analysis FastAPI endpoint
```

Avoid meaningless commit messages:

```text
stuff
fix
changes
wip
agent
```

Do not rewrite another person's commit history unless explicitly instructed.

---

# 52. Pull Requests

When preparing a PR, summarize:

```text
What changed
Why
How to test
API/schema changes
Screenshots if relevant
Known limitations
```

Call out changes that affect other ownership areas.

For example:

> `TutorAnnotation` now uses normalized x/y coordinates. Frontend annotation rendering must convert these to canvas coordinates.

---

# 53. Do Not Invent Missing Product Decisions

Agents may make small implementation decisions.

Agents should **not** independently make major product decisions such as:

* switching away from tldraw
* switching away from FastAPI
* switching framework from Next.js
* replacing the AI provider
* introducing microservices
* replacing the persistence layer
* changing the central tutoring interaction

If such a change appears necessary, flag it to the human developer.

---

# 54. Priority Order

When choosing what to work on, use this priority:

```text
1. End-to-end tutor loop
2. Whiteboard reliability
3. AI work interpretation
4. Correct annotation placement
5. Question generation
6. Course-aware context
7. Demo UX/polish
8. Adaptive learning
9. Persistence
10. Nice-to-have features
```

A polished adaptive mastery dashboard is useless if the AI cannot correctly mark a student's work.

---

# 55. Definition of MVP

The project has reached its minimum successful state when a user can:

1. Open a practice problem.
2. See the problem on the whiteboard.
3. Write a solution by hand.
4. Press a tutor action such as **Check**.
5. Have their current canvas analyzed by the backend.
6. Receive meaningful feedback.
7. See that feedback rendered directly onto the canvas.

Everything else supports this loop.

---

# 56. Final Rule for Agents

When uncertain between a complicated solution and a simple solution that can be demonstrated reliably:

**choose the simple solution.**

When uncertain whether to modify another contributor's area:

**prefer a clean interface over a broad rewrite.**

When creating a branch:

**it MUST begin with `[name]/`.**
