# AGENTS.md

## Purpose

This repository is built by a six-person hackathon team using substantial agentic coding assistance.
This file is the operating manual for coding agents. Read it before meaningful work.
For product-facing work, also read `docs/PRODUCT.md`.
For architecture, API, persistence, shared-schema, AI-integration, or major frontend/backend changes, also read `docs/ARCHITECTURE.md`.
`docs/PRODUCT.md` is authoritative for intended product behavior.
`docs/ARCHITECTURE.md` is authoritative for the current technical direction.
If a task conflicts with either document, tell the human instead of silently redefining the project.

## IMPORTANT:

If you make any architectural or important changes, ensure that you update docs/ARCHITECTURE.md appropriately.

## Product in 30 Seconds

We are building a **persistent, course-aware AI whiteboard tutor**.

```text
Course / Space
    ↓
Saved Whiteboard Sessions
    ↓
Infinite Whiteboard
```

The student solves problems directly on the whiteboard.
The AI understands the course, current problem, handwritten work, and optionally a user-selected region.
The AI responds primarily **on the canvas**, not through a traditional chat interface.
Core loop:

```text
course context
 → generate/import problem
 → clean problem on canvas
 → student works by hand
 → AI interprets work
 → AI marks/hints/explains on canvas
 → session persists
```

Product invariants:

- Canvas-first; no traditional chat UI in the core product.
- Saved whiteboards are persistent working sessions.
- Imported problems should be reconstructed cleanly, not merely pasted as images.
- Course Context includes instructor style, notation, difficulty, covered topics, and question patterns.
- The AI should not silently teach techniques outside the student's course material.
- System, student, and AI canvas content should be distinguishable internally.
- AI canvas actions come from validated structured output.
- The user controls tutoring intensity.
  Read `docs/PRODUCT.md` before changing any of these behaviors.

## Settled Stack

Frontend:

```text
TypeScript + React + Next.js + tldraw
```

Primary target: responsive web, especially iPad Safari.
Backend:

```text
Python + FastAPI + Pydantic
```

Do not replace tldraw, migrate to React Native, replace FastAPI, or introduce a conventional chat UI without explicit human approval.
Private AI-provider keys belong on the backend.

## Git Rules — Non-Negotiable

Never do meaningful work directly on `main`.
Every feature branch MUST follow:

```text
[name]/[feature]
```

Examples:

```text
jaden/canvas-persistence
alex/course-ingestion
sarah/live-tutor
marco/question-generation
```

The first segment is the human developer's name.
If you do not know which human you are working for, **ask before creating a branch**. Do not invent a name.
Do not use branches like `feature/canvas`, `fix/annotations`, `agent-work`, or `backend-update`.
Before editing:

```bash
git status
git branch --show-current
```

Agents must not commit directly to `main`, force-push `main`, rewrite shared history, delete another contributor's branch, or merge their own branch into `main` unless explicitly asked.

## Team Workstreams

### Frontend / Whiteboard

Owns Next.js UI, tldraw, session grid, whiteboard controls, problem display, annotation rendering, Select for AI, and iPad/browser UX.
Works most closely with AI Tutor / Vision.

### AI Tutor / Vision

Owns multimodal interpretation of handwriting, tutor reasoning, error localization, structured responses, and model/prompt reliability.
Works most closely with Frontend / Whiteboard.

### Course Context / RAG

Owns uploads, extraction, chunking/indexing, retrieval, course modeling, and instructor-style signals.
Works most closely with Learning / Question Generation.

### Backend / Infrastructure

Owns FastAPI, APIs, persistence, service wiring, environment configuration, secrets, and deployment plumbing.

### Learning / Question Generation

Owns practice generation, instructor-style matching, difficulty/topic controls, early mastery logic, and future adaptive selection.

### Integration / Generalist

Owns end-to-end functionality, deployment, demo reliability, interface mismatches, and cross-team blockers.

## Shared Interfaces

Critical boundaries:

```text
Frontend ↔ Backend
Whiteboard ↔ Tutor/Vision
Tutor output ↔ Annotation Renderer
Course Context ↔ Question Generation
Persistence ↔ Whiteboard Session
```

When changing a shared interface:

1. identify every consumer
2. update affected types/schemas
3. update tests where practical
4. coordinate with affected teammates
5. verify the end-to-end path
   Do not silently change shared contracts.

## AI and Canvas Rules

Programmatic AI output is untrusted data.
Preferred flow:

```text
canvas + course + problem + tutor request
        ↓
AI model
        ↓
validated structured response
        ↓
frontend renderer
        ↓
tldraw
```

Likely actions: `text`, `math`, `arrow`, `circle`, `underline`, `highlight`, `check`, `cross`.
Do not allow arbitrary model text to execute arbitrary tldraw operations.
At minimum distinguish canvas ownership:

```text
system / problem
student
AI tutor
```

The UX should still feel like one shared notebook.
This distinction supports analyzing only student work, hiding/clearing AI feedback, undoing tutor interventions, and restoring sessions correctly.

## Persistence

A whiteboard session is a persistent working document.
Do not save only a screenshot.
Persist enough interactive state to reopen and continue: tldraw state, student content, AI content, system/problem content, problem association, session metadata, and useful viewport state.
Preview images may exist for session cards but are not the source of truth.

## Course Context

Course Context is not generic RAG.
It should model covered/not-yet-covered topics, instructor notation and terminology, question wording/formatting, typical difficulty, common question structures, and authentic examples.
The same context informs tutoring and question generation.
If the AI wants to use a technique outside course materials, it should pause and tell the user rather than silently introducing it.
See `docs/PRODUCT.md`.

## Tutor Behavior

Core actions:

```text
Mark
Hint
Explain
I'm Stuck
```

They represent different pedagogical behaviors, not identical prompts with different labels.
Optional live-tutor thresholds:

```text
Instant
2 Seconds
New Line
```

These change when the tutor intervenes; they are not cosmetic settings.
The user can also **Select for AI** to direct the tutor at a specific canvas region.
Do not design around making users describe visual positions in text.

## Scope Discipline

Make the smallest coherent change that solves the task.
Do not use a narrow feature request as permission to replace state management, reorganize the repo, rewrite another subsystem, change the database, replace tldraw, or reformat the project.
Hackathon code may be imperfect. Working code has value.
Refactor unrelated code only for a concrete reason.

## Multi-Agent Development

Assume several humans and agents are working in parallel.
Before broad changes:

- inspect the repository and current branch
- search for existing implementations
- identify subsystem ownership
- inspect shared types/schemas
- avoid unnecessary edits to central files
  Likely conflict hotspots include:

```text
frontend/app/page.tsx
frontend/package.json
backend/app/main.py
README.md
```

Prefer focused modules over accumulating logic in central files.

## What Agents May Decide

Agents may make normal implementation decisions: helper names, component decomposition, internal utilities/types, straightforward error handling, ordinary testing strategy, and small UI details consistent with `PRODUCT.md`.
Prefer existing repository conventions.

## What Agents Must Escalate

Ask the human before:

- changing Next.js, tldraw, or FastAPI
- introducing React Native as the primary frontend
- adding traditional chat
- changing persistence semantics
- redefining Course Context
- changing the core tutor interaction
- introducing microservices
- replacing a major persistence technology
- substantially changing shared schemas without coordination
- removing a core planned feature
- adding a major framework
- replacing another teammate's subsystem
- changing the Course → Sessions → Whiteboard hierarchy
- changing imported-problem reconstruction behavior
  Do not confuse an agent's confidence with authority to redesign the product.

## Before You Code

Answer:

```text
1. What user flow does this support?
2. Which subsystem owns it?
3. Does an implementation/interface already exist?
4. Am I changing a shared contract?
5. Could another teammate be working here?
6. What is the simplest solution consistent with PRODUCT.md?
7. How will I verify it?
8. Does this preserve the canvas-first experience?
```

If ambiguity changes product behavior, ask the human.
If it is only an implementation detail, make a reasonable choice and continue.

## Dependencies

Before adding one, ask:

1. Is something already installed that solves this?
2. Does the framework provide it?
3. Does it materially accelerate development?
4. Does it create browser/iPad risk?
5. Does it add setup burden for teammates?
   Avoid redundant state managers, HTTP clients, UI systems, validation libraries, canvas systems, and persistence layers.

## Frontend Conventions

Use TypeScript.
Prefer functional React components, explicit types, clear feature boundaries, local state when practical, and API access behind a small client/service layer.
Avoid unexplained `any`, massive page components, frontend provider secrets, duplicated backend logic, and direct private AI SDK calls from the browser.

## Backend Conventions

Use FastAPI routers, Pydantic request/response models, modern Python type hints, service functions, and clear error handling.
Prefer thin route handlers:

```python
@router.post("/analyze", response_model=TutorResponse)
async def analyze(mode: TutorMode, canvas_image: bytes) -> TutorResponse:
    return await tutor_service.analyze(request)
```

Do not put hundreds of lines of AI logic in route handlers.

## Error Handling and Security

Users should not see stack traces, raw provider errors, secret values, or parser internals.
Handle timeouts, rate limits, malformed AI output, empty responses, uncertainty, and image failures gracefully.
One failed model call must not destroy a persistent session.
Never commit API keys, passwords, private tokens, credentials, or secret connection strings.
Use environment variables and `.env.example` placeholders.
Treat user uploads, user text, and model output as untrusted.

## Testing

Prioritize deterministic/shared logic:

- Pydantic schemas and API contracts
- annotation validation
- coordinate transforms
- canvas serialization/session persistence
- course-context utilities
- question-generation schemas
  Manual validation of the core canvas flow is essential.
  Critical end-to-end path:

```text
open course
 → open/create whiteboard
 → generate/import problem
 → write on canvas
 → request tutor feedback
 → FastAPI + AI analysis
 → structured response validates
 → annotation appears correctly
 → reload
 → state persists
```

## Priority Order

```text
1. End-to-end tutor loop
2. Whiteboard reliability
3. Persistent session restore
4. Accurate student-work interpretation
5. Correct annotation placement
6. Course-aware question generation
7. Course ingestion/context
8. Imported problem reconstruction
9. Select for AI
10. Tutor-mode quality
11. Demo UX/polish
12. Live tutor
13. Voice
14. Rich student analytics
15. Realistic AI handwriting
```

## iPad / Browser

The product is web-first and should work especially well on iPad Safari.
Most development can happen on desktop, but periodically validate touch, stylus behavior, accidental scrolling/zooming, landscape layout, canvas performance, selection, and annotation readability.

## Finishing a Task

Before completion:

1. run relevant tests/checks
2. inspect `git status` and `git diff`
3. remove debug code
4. verify no secrets/unrelated files were added
5. manually test the relevant flow where practical
   Final handoff should state:

- what changed and why
- important files changed
- shared interfaces changed
- how to test
- commands run
- known limitations
- whether another teammate must coordinate

## Definition of Done

A meaningful feature should be:

```text
implemented
+ integrated enough to use
+ typed/validated
+ reasonably tested
+ consistent with PRODUCT.md
+ consistent with ARCHITECTURE.md
+ understandable by the next teammate
```

## Commit Discipline

Commit frequently as you complete coherent units of work.

Do not wait until the entire feature is finished to make one large commit.

Each commit should be **atomic**:

- one logical change
- independently understandable
- ideally independently buildable/testable
- no unrelated refactors
- no debug files or accidental formatting changes

Good commit boundaries include:

- add tutor response schema
- add FastAPI tutor endpoint
- add annotation renderer
- wire renderer to tutor response
- add session persistence test

Bad commit boundaries include:

- "frontend + backend + cleanup + random fixes"
- hundreds of unrelated changed lines
- mixing formatting changes with feature logic

Before each commit:

1. Run `git status`.
2. Inspect `git diff`.
3. Stage only files/hunks belonging to that logical change.
4. Run relevant tests/type checks if practical.
5. Commit with a descriptive imperative message.

Prefer:

````text
Add tutor annotation schema
Implement canvas annotation renderer
Persist tldraw session state
Fix normalized annotation coordinates

## Final Heuristics
Choose a reliable demo over clever abstraction.
Choose course/canvas-grounded AI behavior over generic AI behavior.
Prefer spatial canvas interaction over chat-like responses.
If a decision changes what the user experiences or what another subsystem must assume, ask the human.
And always:
```text
Every feature branch MUST be [name]/[feature].
````
