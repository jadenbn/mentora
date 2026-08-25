# LEARNING_ENGINE.md

## Purpose

This document describes the **learning engine**: the part of the system that
decides *what a student should work on next*, tracks *what they actually know*,
and keeps both grounded in the student's real course material.

**This describes what is built**, not product intent. For product intent read
`PRODUCT.md`; for the whole backend's shape read `ARCHITECTURE.md`; for the
tutor path specifically read `TUTOR_AGENT.md`.

Everything here lives under `backend/app/`:

| Concern | Module |
| --- | --- |
| Skill taxonomy: build, validate, seed, merge | `services/taxonomy.py` |
| Taxonomy generation from course text | `services/skill_generation.py` |
| Mastery math (pure, no I/O) | `services/mastery.py` |
| Shared decayed read of one skill | `services/skill_progress.py` |
| What to serve next | `services/selection.py` |
| Attempt ingestion + student model | `services/student_model_service.py` |
| Tutor grade → attempt fields | `services/attempt_grading.py` |
| HTTP surface | `api/learning.py` |
| Dev dashboard + skills import | `api/dev.py` |
| Startup wiring | `bootstrap.py` |

---

## 1. The loop

The engine's whole reason to exist is one cycle. `POST /next-problem` runs it
end to end:

```text
   ┌─────────────────────────────────────────────────────────────┐
   │                                                             │
   ▼                                                             │
select_next()          what skill, at what difficulty, avoiding  │
  │                    which forms, probing which misconception  │
  ▼                                                              │
search_course()        rank the course's own chunks against the  │
  │                    skill's retrieval query → target document │
  ▼                                                              │
QuestionService        generate a problem grounded in that       │
  .generate()          document's real text                      │
  │                                                              │
  ▼                                                              │
set_problem_skills()   tag the problem server-side with the      │
  │                    skill selection actually chose            │
  ▼                                                              │
student works, tutor grades the canvas                           │
  │                                                              │
  ▼                                                              │
to_attempt_grading()   WorkStatus → correct/partial/errors       │
  │                                                              │
  ▼                                                              │
record_attempt()       look up the problem's real skills, update │
  │                    mastery, bleed onto prereqs, log attempt  │
  └──────────────────────────────────────────────────────────────┘
```

The closing edge is the point. Selection's choice is written into
`problem_skills` at generation time, so when the attempt comes back the engine
knows what it *actually served* — it does not have to trust the client to say.

---

## 2. Data model

Five SQLModel tables plus one raw-sqlite3 bridge table, all in the same SQLite
file (`mentora.db`, override with `MENTORA_DB_PATH`).

### `Skill` — `models/skill.py`

One addressable unit of a course's taxonomy.

| Field | Meaning |
| --- | --- |
| `id` | `"calc1.derivatives.chain-rule"` — course-prefixed, normalized |
| `course_id` | indexed; a skill belongs to exactly one course |
| `name`, `description` | human-facing, and fed to the question generator |
| `difficulty_band` | 0..1, the skill's intrinsic difficulty |
| `prereqs` | list of skill ids; the DAG edges |
| `keywords` | retrieval vocabulary the *textbook* uses that `name` may not |
| `question_forms` | shapes this skill's questions take — used as *avoid* hints |
| `origin` | `seed` (hand-authored) or `generated` (from course text) |
| `created_at` | never rewritten on update — lets the dashboard flag new skills |

### `SkillState` — `models/skill_state.py`

One student's live estimate for one skill. Primary key `(student_id, skill_id)`.

`mastery` (default 0.5), `attempts`, `correct_unassisted`, `streak`
(signed — positive is a win streak, negative a loss streak),
`misconception_counts` (JSON tag→count), `last_seen`.

### `Attempt` — `models/attempt.py`

**Immutable.** Never edited after insert. This is the ledger — stored mastery is
always a function of this log alone, which is what makes recomputation possible
if the constants in `mastery.py` change.

Holds `expected_skills` (the *server-resolved* list, not the client's),
`difficulty`, `correct`, `partial`, `hints_used`, `total_time_ms`, and `errors`
— only those that survived the attribution guard (§7).

### `StudentProfile` — `models/student_profile.py`

Slow-moving, course-scoped: `global_ability` (default 0.5) and `hint_reliance`.
`global_ability` seeds a never-attempted skill's mastery, so cold start is not
blind.

### `CourseTaxonomyVersion` / `CourseGenerationVersion`

Content-hash guards, so re-seeding and re-generation are no-ops when nothing
changed.

### `problem_skills` — `database.py`

Raw-sqlite3 bridge: `(problem_id, skill_id, ordinal)`. Written by
`set_problem_skills()` at generation time, read by `get_problem_skills()` at
ingestion time. This is the table that makes server-side attribution possible.

### Enums — `models/enums.py`

`MisconceptionTag` is a **closed, subject-agnostic vocabulary** — the same five
tags must mean the same thing in every course, because one vocabulary is shared
across every taxonomy:

`conceptual-error` (wrong idea/method) · `procedural-error` (right idea,
executed wrong) · `careless-error` (right idea and method, slipped) ·
`incomplete` · `no-attempt`

---

## 3. Taxonomy

### Authoring

Seed taxonomies are hand-authored JSON in `backend/data/courses/{course_id}.json`.
Four ship today: `calc1`, `chem1`, `cs1`, `phys1`.

### One builder for every source

`build_taxonomy(course_id, raw_skills, origin)` is the **single** path from raw
dicts to validated `Skill` objects. Hand-authored JSON and LLM output take the
same road, so a generated skill is held to exactly the rules a seeded one is.

It does two things:

**Normalize** — `normalize_slug()` lowercases, replaces invalid characters with
hyphens, collapses repeats, strips edges, and course-prefixes. It is idempotent,
so normalizing an already-normalized id is a no-op.

**Validate** — `validate_taxonomy()` raises `TaxonomyError` on:
- duplicate ids after normalization
- `difficulty_band` outside `[0, 1]`
- a `keywords`/`question_forms` list over 12 entries, or an entry over 80 chars,
  or a non-string/empty entry (these are free-form and reach an embedding call,
  so they are bounded before they get there)
- an unresolved prerequisite
- **any cycle** — DFS with a visiting set; the error names the cycle path

### Seeding: `seed_all_courses()`

Runs once on startup (`bootstrap.py`). Safe to call repeatedly: a course is
re-seeded only when its JSON's content hash differs from what was last seeded.
Editing a course file and restarting therefore *takes effect*, instead of being
silently ignored because rows already exist.

Re-seeding deletes and reinserts that course's **seed** skills. `SkillState` is
keyed by `skill_id` in a different table and is left untouched, so per-student
progress survives. A skill renamed or removed by the edit orphans its
`SkillState` — that is **logged as a warning**, not dropped quietly.

### Merging: `merge_generated()`

Additive upsert for a generated batch.

- A produced id matching an existing **`generated`** skill updates its
  describing fields (name, description, difficulty, keywords, question_forms).
- A produced id colliding with a **`seed`** skill is **skipped and logged** —
  seed skills are read-only to generation.
- **Nothing is ever deleted here.** Removal is a separate, deliberate operation
  and is out of scope.
- `SkillState` is never touched — it survives any update to the `Skill` row it
  names.

Crucially, it validates the graph the merge would *produce* — every untouched
existing skill plus the batch, as one unit. So a new skill's prereq on an
existing skill resolves, and no addition can introduce a cycle spanning old and
new skills rather than just within the batch.

Returns a `MergeReport(added, updated, blocked_seed_collisions)`.

---

## 4. Skill generation

The steady-state strategy is **emergent**: skill discovery is meant to piggyback
on calls the system already makes (question generation, grading), so ongoing
growth costs no extra LLM spend.

**Uploading a course document does not create skills.** Ingestion extracts,
chunks, and indexes text — nothing more.

Two functions exist in `services/skill_generation.py`:

### `bootstrap_first_skill()` — the one deliberate call

Fired from `POST /next-problem` **only** when a course has zero `Skill` rows and
selection has nothing to pick. This is the single gap piggybacking cannot fill:
there is no prior skill for question generation to be grounded by, so there is
nothing to piggyback on yet.

Deliberately cheap — up to 6 chunks / 6,000 chars from the *first* document, not
course-wide sampling. Its only job is giving selection **one** skill to start
from. After it succeeds the path never runs again for that course.

It is **best-effort and silent**: if `GEMINI_API_KEY` is unset or the call
fails, it logs and returns, and the caller's existing 404 for "no unlocked
skills" stands. It never turns into a 500.

### `generate_taxonomy_for_course()` — infrastructure, not wired

Whole-course generation: samples chunk text round-robin across every document
(so one large file can't crowd out the others), char-capped, guarded by a
content hash of the document-id set so an unchanged course makes no model call.

Tested and working, but **nothing calls it automatically** today. It's kept for
a manual "regenerate this course's taxonomy" action or a switch back to eager
generation.

---

## 5. Mastery math

`services/mastery.py` is **pure** — no database, no I/O, no provider calls. That
is deliberate: it makes the estimator property-testable and keeps stored mastery
a function of the attempt log alone.

### Scoring an outcome

| Outcome | Score |
| --- | --- |
| Correct, no hints | 1.00 |
| Correct, one hint | 0.70 |
| Correct, multiple hints | 0.45 |
| Partial | 0.15 |
| Incorrect | 0.00 |

### The update rule — and why it moves toward a *residual*

```python
expected = 1 / (1 + exp(-4.0 * (mastery - difficulty)))
mastery += learning_rate(attempts) * (score - expected)
```

This is the single most load-bearing design decision in the engine, so it's
worth stating why.

Selection **always serves difficulty at or above current mastery** (§6). A
student whose mastery estimate has caught up to their true ability therefore
succeeds only ~50% of the time *by construction*. An EWMA moving toward raw
score would get permanently trapped below true ability, chasing a fixed point
defined by `P(correct) == mastery` rather than by ability itself.

Moving toward the **residual between actual and expected score** is
difficulty-invariant at that fixed point instead. That is what lets mastery
actually reach a confident student's true ability rather than plateauing well
below it.

### Learning rate

```python
alpha = max(0.03, 0.50 / (1 + 0.35 * attempts))
```

Big steps when evidence is thin, small steps once it isn't.

The `0.03` floor is empirical. A `0.15` floor never let the estimate settle: it
is reached by ~7 attempts and holds forever after, so every later attempt kept
taking a step as large as a cold-start one. Per-attempt score has real variance
around its expectation (binary correct/incorrect plus hint-tier quantization),
so a floor that large meant mastery never converged — it stayed a bounded
high-amplitude random walk, oscillating 0.15–0.3 late in a skill's history even
against a stable true ability.

Dropping it to `0.03` cut late-stage oscillation ~3–4× (std ~0.09–0.11 → ~0.02–0.03)
and worst-case final-estimate error from 0.23 → <0.08 across repeated simulated
runs, with **no** measurable cost to early responsiveness (root-skill unlock
timing unchanged). Verified by `backend/scripts/simulate.py`.

### Bounds, decay, confidence, bleed

- **Bounds** — mastery is clamped to `[0.02, 0.98]`. Never fully certain either way.
- **Decay** — `apply_decay()` relaxes mastery toward 0.5 with a 14-day halflife.
  Applied **on read only, never written back**, so mastery stays rebuildable
  from the log.
- **Confidence** — `1 - exp(-attempts / 4)`. 0 at no attempts, → 1 with more.
  Reported alongside mastery so a consumer can tell "0.8, barely observed" from
  "0.8, well established."
- **Prerequisite bleed** — 10% of a mastery delta bleeds onto direct
  prerequisites, one level only.

---

## 6. Selection

`services/selection.py` is **read-only** — nothing here writes state. It reads
what ingestion recorded and derives a spec.

### Step 1 — unlock gating

A skill is unlocked when **every** prerequisite has decayed mastery ≥ `0.60`.
Locked skills are never served. If nothing is unlocked, `select_next()` returns
`None` (the API turns that into a 404).

### Step 2 — priority

```python
priority = 0.60 * (1 - mastery)            # urgency: weak skills first
         + 0.25 * min(days_since / 7, 1)   # staleness: nudge the neglected
         - 0.40 if recently served         # recency: don't hammer one skill
```

The recency penalty applies to the primary skill of the last 2 attempts.

### Step 3 — the forced-review floor

If the last **3** picks were all skills below mastery `0.70`, and any unlocked
skill sits at ≥ `0.70`, selection forces a review pick and flags
`is_review=True`.

Without this, priority's urgency term keeps a struggling student pinned to their
weakest material indefinitely. The floor guarantees a break.

### Step 4 — difficulty

```python
target_difficulty = clamp(mastery + 0.15, 0.1, 0.9)
```

Always slightly above current estimate — the productive-struggle band, and the
reason the residual-based update in §5 is necessary.

### Output: `GenerationSpec`

| Field | Purpose |
| --- | --- |
| `skill_id`, `skill_name`, `skill_description` | what to teach |
| `target_difficulty` | how hard |
| `target_misconception` | the student's top misconception on this skill — **only if seen ≥ 3 times**, so one bad read can't steer generation |
| `avoid_forms` | question forms to vary away from |
| `retrieval_query` | `name + description + keywords`, for course retrieval |
| `prereq_mastery` | what the student brings to this skill |
| `is_review` | whether the review floor fired |

### `SkillProgress` — the shared read

`services/skill_progress.py` exists so selection and the student-model report
can't drift. Both need the same thing: decayed mastery as of now, attempt count,
and misconceptions ranked by frequency. It's computed once, in one place.

It deliberately returns the **full** ranked misconception list, un-truncated —
selection wants a single count-gated tag, a report wants the top few ungated, so
each caller derives its own view rather than the shared type guessing.

---

## 7. Attempt ingestion

`student_model_service.record_attempt()`. Two guards run before any state moves.

### Guard 1 — server-side skill attribution

If a repository is supplied and the problem has `problem_skills` rows, **those
rows are the source of truth**. The client's `expected_skills` is only a hint,
cross-checked and logged on mismatch.

A client can no longer attribute an attempt to any skill it names.

Problems with no row (legacy, or externally authored) fall back to the client's
list — and that fallback is logged, so it's visible rather than silent.

Any skill id not in the course's taxonomy raises `UnknownSkillError` → HTTP 400.

### Guard 2 — the error-attribution guard

An error naming a skill **outside** this attempt's declared `expected_skills` is
dropped and logged, never trusted. Without it, one misread canvas from grading
could corrupt a skill the student never touched, with nothing in the table
recording why. The count comes back as `dropped_errors` on the response.

### Then, per skill

1. Get-or-create `SkillState`, seeded at the profile's `global_ability`.
2. `update_mastery()`; record the delta.
3. `attempts += 1`; `correct_unassisted += 1` if correct with zero hints.
4. Update the signed streak.
5. Increment `misconception_counts` — by **reassignment**, not in-place mutation.
   SQLAlchemy doesn't track in-place changes to a plain JSON column's contents,
   only attribute reassignment, so an in-place update is silently dropped on
   commit.
6. `last_seen = now`.

### Then, prerequisites

Deltas bleed onto direct prerequisites (one level), applied **after** every
primary skill is updated — so a skill that is both a target and a prerequisite
of another target isn't double-counted against a stale mastery. A skill already
updated as a primary target is skipped.

### Then, the ledger

One immutable `Attempt` row, holding the server-resolved skills and only the
surviving errors. Single commit.

Returns `AttemptResult(attempt_id, updated_skills, dropped_errors)`.

---

## 8. The grading bridge

`services/attempt_grading.py` — a pure function, no DB, no provider call. The
tutor grades a canvas; the engine records a per-skill attempt; nothing else in
the codebase joins the two.

| `WorkStatus` | Result |
| --- | --- |
| `uncertain` | **`None` — do not record.** The tutor never actually graded the canvas, so there is nothing to feed the model. |
| `correct` | `correct=True`, no errors |
| `partial` | `partial=True`, `INCOMPLETE` on each expected skill |
| anything else | `correct=False`, `CONCEPTUAL_ERROR` on each expected skill |

**Known gap, stated plainly:** `TutorResponse` carries no signal finer than
correct/incorrect/partial/uncertain, so every incorrect attempt is
conservatively tagged `CONCEPTUAL_ERROR`. Real misconception granularity needs
the tutor's *single existing model call* to emit it directly — extending
`TutorPlan`, not adding a second round trip. That's a change to
`schemas/tutor.py` and `prompts/tutor.py`, owned by the tutor path.

Until then, `target_misconception` in a `GenerationSpec` is dominated by
`conceptual-error`, and its 3-observation gate is doing less work than it will
once the signal is real.

---

## 9. API surface

All under `/api/courses/{course_id}`, registered by `bootstrap.py`.

| Route | Does |
| --- | --- |
| `POST /attempts` | Record an attempt, update mastery, return per-skill deltas. 400 on unknown skills. |
| `GET /student-model?student_id=` | Current decayed mastery per **attempted** skill, with confidence and top-3 misconceptions. |
| `GET /skills-overview?student_id=` | **Every** skill — including untouched ones at seed mastery — with unlock state, origin, `is_recent`, and `next_skill_id`. The dashboard view. |
| `GET /next-problem-spec?student_id=` | What the next problem *should* target, without generating it. Cheap; no model call. 404 if nothing unlocked. |
| `POST /next-problem?student_id=` | The whole loop: select → ground → generate → tag. Returns problem + spec. |

`GET /skills-overview` is defensive by design: if `select_next()` throws it logs
and returns `next_skill_id: null` rather than failing. A read-only view must
never break because selection did.

`POST /next-problem` failure modes: 404 no unlocked skills / document not found ·
409 no indexed documents to ground in · 502 retrieval failed · 503 retrieval not
configured.

Document grounding falls back gracefully: rank the course's chunks against the
skill's `retrieval_query` and take the top chunk's document; if retrieval is
unconfigured or returns nothing, use the most recently updated document, so a
keyless dev demo of a small course still works.

### Dev-only, not in the OpenAPI schema

| Route | Does |
| --- | --- |
| `GET /dev/dashboard` | Self-contained HTML dashboard: every skill, mastery bars, unlock state, and buttons to fire synthetic correct/partial/incorrect attempts and watch mastery move. |
| `POST /dev/courses/{id}/skills/import` | Paste a raw skills batch straight in. Runs the same `build_taxonomy → merge_generated` path real generation uses, always tagged `generated`, seed ids protected. The fastest way to test a specific graph shape without spending a model call. |

---

## 10. Invariants worth protecting

1. **Mastery is a pure function of the attempt log.** Decay is read-time only.
   Change a constant in `mastery.py` and every estimate is recomputable.
2. **`Attempt` is immutable.** Never edited after insert.
3. **`mastery.py` has no I/O.** Property-testable in isolation, and it stays
   that way.
4. **Selection never writes.** If it starts writing, "what would you serve me
   next" stops being a safe question to ask.
5. **The client cannot attribute its own attempts.** `problem_skills` decides.
6. **Seed skills are read-only to generation.** Only a human editing course JSON
   changes them.
7. **Every taxonomy goes through `build_taxonomy`.** Generated output is held to
   the rules hand-authored JSON is.
8. **Generation never deletes.** Additive only.
9. **`SkillState` outlives taxonomy edits.** Orphaning is logged, not silent.
10. **One misconception vocabulary across all courses.** Tags are
    subject-agnostic or they mean nothing.

---

## 11. Known gaps

- **Misconception granularity is a stub.** See §8. The single largest
  correctness gap, and it is not fixable from inside the engine.
- **Emergent generation isn't wired yet.** Only `bootstrap_first_skill` fires.
  The piggybacking-on-question-generation path that grows a taxonomy past skill
  one is designed but not built; `generate_taxonomy_for_course` is the working
  fallback nothing calls.
- **`hint_reliance` is stored but unused.** Nothing reads it yet.
- **Whole-course generation samples rather than summarizes.** A course whose
  combined text badly exceeds the char cap wants map-reduce summarization.
- **Prereq bleed is one level.** A deep chain doesn't propagate.
- **Selection is single-skill.** Every spec targets exactly one skill; there's
  no multi-skill or integrative problem.

---

## 12. Verifying it works

Unit and integration tests: `backend/tests/README.md` (§ "Testing the learning
engine") — the layout table, what each file covers, and the closed-loop test.

Behavioral simulation: `backend/scripts/simulate.py` drives the *actual*
selection policy against the real `calc1` taxonomy with synthetic students, and
gates on mastery convergence, rank correlation, skill starvation, and whether
forced review ever fires. That's the tool that justified the `ALPHA_FLOOR`
change in §5, and the one to run when changing any constant in `mastery.py` or
`selection.py`.

Manual: `GET /dev/dashboard`.
