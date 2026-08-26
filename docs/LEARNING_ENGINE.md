# LEARNING_ENGINE.md

The tutor's brain: a per-course topic list, and a per-student read of how
they're doing on each one. **It has no user interface.** No practice button,
no mastery readout, no "what do I know" screen. The student uploads a
document and asks for a question; the engine silently decides which topic
and how hard, and later folds a graded attempt back into what it knows.

For product intent read `PRODUCT.md`; for the backend's overall shape read
`ARCHITECTURE.md` §47; for the tutor read `TUTOR_AGENT.md`.

| Concern | Module |
| --- | --- |
| Per-topic accuracy math (pure, no I/O) | `services/accuracy.py` |
| Which topic to target next, and how hard | `services/selection.py` |
| A student's overall tendencies, derived from the ledger | `services/profile.py` |
| Attempt ingestion, and the dashboard's overview query | `services/student_model_service.py` |
| Which skills a problem exercises | `services/attribution.py` |
| Topic list: build, validate, seed, append | `services/taxonomy.py` |
| The one generation route; the engine is consulted here | `api/questions.py` |
| Grading and the dashboard's HTTP surface | `api/learning.py`, `api/dev.py` |

---

## 1. The loop

```text
student types a request, or leaves it blank
        |
        +-- blank -> pick_topic()      picks a topic + difficulty from this
        |                                student's per-topic accuracy
        +-- typed -> get_profile()     contributes a difficulty level from
        |                                overall accuracy; the student's own
        |                                topic wins
        v
QuestionService.generate()    a grounded problem; the model also names the
                                skill(s) it thinks the question exercises
        |
        +-- names an existing topic -> attributed to it
        +-- names something new     -> appended to the skills file (§4)
        v
set_problem_skills() + set_problem_difficulty()
        |
        v
student works; POST /work sends the canvas
        |
tutor grades it       the server calls the tutor; the client never says
        |              whether the work was right
        v
record_attempt()      push the outcome into the topic's rolling window
```

**There is no "next problem" route.** Topic selection happens inside
`POST /questions/generate` — that is the entire mechanism behind "practice
next topic": an empty request is a valid one, and the engine fills in the
rest.

**Grading happens server-side.** `POST /work` takes the canvas and returns
the tutor's response; nothing the browser sends scores the student's work.

---

## 2. Data model

Five SQLModel tables plus a raw-sqlite3 repository for documents, chunks and
generated problems. Same SQLite file (`mentora.db`, override `MENTORA_DB_PATH`).

**`Skill`** — one topic in a course's flat list. Id is course-prefixed and
normalized (`calc1.derivatives.chain-rule`). No prerequisite field — topics
are flat. Carries `keywords` (retrieval vocabulary), `question_forms`,
`difficulty_band`, and `origin` (`seed` hand-authored, or `generated` via the
piggyback).

**`SkillState`** — one student's rolling window for one topic, keyed
`(student_id, skill_id)`. `recent_outcomes`: the most recent 8 scores, oldest
first — accuracy is their mean, `None` when empty. `attempts` and
`hints_used` count everything, unbounded by the window. `last_seen` is null
until the topic is actually practised.

**`Attempt`** — immutable. The ledger. `services/profile.py` derives the
student profile from this alone. Unique on `(student_id, problem_id)`: one
problem, one attempt.

**`ProblemSkill`** — which topics a problem exercises, `skill_id` a real
foreign key to `skill.id`. This is the table the attribution guarantee rests
on, which is why it lives beside `Skill` rather than in the raw repository.

**`CourseTaxonomyVersion`** — a content hash of the course's skills file, so
re-seeding (and `append_skills`) are no-ops when nothing actually changed.

---

## 3. Accuracy, not mastery

`services/accuracy.py` is pure — no database, no I/O.

| Outcome | Score |
| --- | --- |
| Correct, no hints | 1.0 |
| Correct, with a hint | 0.6 |
| Partial | 0.3 |
| Incorrect | 0.0 |

Accuracy is the mean of a topic's most recent 8 scores
(`SkillState.recent_outcomes`, capped by `push_outcome`). `has_signal`
gates on `attempts >= MIN_ATTEMPTS_FOR_SIGNAL` (2) — below that, a reading
is too thin to act on and callers fall back to a default.

This replaced an Elo/IRT-style estimator (a residual update toward the gap
between actual and expected score, with read-time decay and a confidence
function). That estimator was doing real, correct work — but the engine
has no UI to spend the extra precision on, and a rolling window is simpler
to reason about, to explain, and to get right. `docs/PRODUCT.md` §23 also
asks the MVP to track exactly this: attempts, correct/incorrect, hints used
— counters, not a fitted ability model.

---

## 4. Topics come from the questions themselves

**Question generation may read the topic list and attribute to topics that
exist. It creates a new one only through the same validated path every other
topic source uses — never silently.**

Each skill the model names in `QuestionPlan.skills` resolves one of three
ways, in `QuestionService._attribute_skills`:

1. **Exact match** — the normalized id matches an existing topic.
2. **Name-similarity match** — `taxonomy.canonical_key(name)` matches an
   existing topic's key. This is a cheap string check (lowercase, drop
   stopwords, sort the remaining words), not an embedding call: "The Chain
   Rule", "chain rule", and "Rule, Chain" all reduce to the same key, so a
   model re-describing an existing topic in different words doesn't mint a
   duplicate.
3. **Genuinely new** — goes through `build_taxonomy` (the same normalizer
   and validator hand-authored course JSON uses) and then
   `taxonomy.append_skills`, which writes the entry into
   `data/courses/{course_id}.json` before inserting it. **The file is the
   source of truth; the database is its mirror.**

A malformed batch (e.g. two entries colliding after normalization) raises
`TaxonomyError` inside `_attribute_skills`. It's caught and logged there —
the taxonomy write is a side effect of generation, not the thing the student
asked for, so it never costs them the problem.

**Cold start.** A course with no topics yet has nothing for `pick_topic` to
select; `POST /questions/generate` falls back to "write a question grounded
in this material" with no required topic, and the model's own read seeds the
first one or two topics through the same piggyback path. No separate
bootstrap call exists.

---

## 5. Selection

`services/selection.py` is read-only, and it is a function
`api/questions.py` calls — not a route of its own.

**Priority** — topics are flat, so there is no unlock gate:

```python
attempts == 0:  W_COVERAGE                                # 0.20
otherwise:      W_WEAKNESS * (1 - accuracy)                # 0.60
              + W_STALENESS * min(days_since / 7, 1)       # 0.25
              - W_RECENCY_PENALTY if recently served       # 0.40
```

Coverage and weakness are separate terms, and that separation is load-bearing.
An earlier, gated version of this scored "never attempted" staleness at a
full 1.0 — a term meaning "decayed since practice" — so an untouched topic
(0.550) beat a topic the student was actively failing (0.480). Novelty beat
remediation, always. Ties break toward lower `difficulty_band`, so a cold
student starts at the easiest topic rather than wherever the query happened
to order the rows.

**Difficulty** — once a topic has enough attempts for a signal, target its
own recent accuracy, clamped to `[0.15, 0.85]`; otherwise a moderate 0.5
default. There is no `mastery + offset` productive-struggle formula here —
accuracy already sits where a residual estimator's fixed point would.

**Why no gate.** A gated design (unlock at mastery ≥ 0.60, served difficulty
always above the estimate) meant a student whose true ability settled around
0.50 could never clear the threshold — the estimate was correct, the gate
was wrong. Simulation showed an average student reaching 3 of 15 topics under
that design. A flat pool has no such wall.

---

## 6. Student profile

`services/profile.py` — not a stored row. Computed on read from the
`Attempt` ledger: total attempts, overall accuracy (once `attempts >= 3`),
hint rate, and topics touched. It can never drift from what actually
happened, and there's no migration if the definition changes.

Used only when a student types their own question request: `pick_topic`
can't run (there's no topic yet to look up a per-topic accuracy for), so
`difficulty_hint(profile)` supplies a course-wide difficulty level instead.

---

## 7. Attempt ingestion

`student_model_service.record_attempt()`.

1. **Already attempted?** Return the original attempt unchanged. The
   whiteboard posts on every "mark", so repeats are expected traffic;
   counting them again would let ten marks on one canvas all count toward
   accuracy.
2. **Whose skills?** `ProblemSkill` rows win. The client's `expected_skills`
   is a hint, cross-checked and logged on mismatch. Unknown skill ids raise
   `UnknownSkillError` → HTTP 400.
3. **Per skill** — push the outcome score into `recent_outcomes` (capped at
   8), increment `attempts` and, if a hint was used, `hints_used`. Stamp
   `last_seen`.
4. **Ledger** — one immutable `Attempt`. Single commit.

No prerequisite bleed: there's no prerequisite graph to bleed onto.

---

## 8. API

Under `/api/courses/{course_id}`:

| Route | Does |
| --- | --- |
| `POST /questions/generate` | The one generation path. Engine consulted implicitly (§1). |
| `POST /work` | Grade a canvas and record the attempt. |
| `GET /skills-overview` | Every topic with this student's accuracy. Dev dashboard only. |

`POST /work` records only when `mode=mark` and the tutor's status is not
`uncertain`. A hint is not a graded attempt, and `uncertain` means the tutor
never read the canvas.

Dev-only, not in the OpenAPI schema:

| Route | Does |
| --- | --- |
| `GET /dev/dashboard` | Every topic, accuracy, origin, and synthetic attempts. |
| `POST /dev/courses/{id}/attempts` | Record an attempt from a stated outcome. |
| `POST /dev/courses/{id}/skills/import` | Paste a topic batch straight into the skills file. |

`POST /dev/courses/{id}/attempts` takes `correct` from its caller, which is
exactly why it is not on the product API.

**Auth.** `MENTORA_API_KEY`, when set, is required on `/api` and `/dev`. It
authenticates the *caller*, not the student — `student_id` is still whatever
the request says, so any key holder can read or write any student's model.
Per-student identity needs a real user system.

---

## 9. Invariants

| Invariant | Enforced by |
| --- | --- |
| Question generation never creates a topic outside `build_taxonomy` | `test_question_service.py::test_generation_identifies_a_new_topic_via_the_piggyback` |
| A differently-worded name resolves to the same topic, not a duplicate | `test_question_service.py::test_a_differently_worded_name_resolves_to_the_same_topic` |
| A malformed skill batch never fails the problem request | `test_question_service.py::test_a_malformed_skill_batch_does_not_fail_the_problem_request` |
| A problem cannot be attributed to a topic that doesn't exist | `test_attribution.py`, plus the FK on `ProblemSkill.skill_id` |
| Seed topics are never overwritten by the piggyback | `test_question_service.py::test_generation_never_overwrites_a_seed_skill` |
| The client cannot score its own work | `test_work_api.py::test_a_correct_mark_records_an_attempt_the_client_never_scored` |
| One problem, one attempt | `test_student_model_service.py::test_reposting_the_same_problem_does_not_move_accuracy_again` |
| The recent-outcomes window is capped, attempt count is not | `test_student_model_service.py::test_the_window_caps_at_eight_outcomes` |
| Coverage and weakness are separate priority terms | `test_selection.py::test_a_failing_topic_outranks_an_untouched_one` |

---

## 10. What was cut, and why

An earlier version of this engine was an adaptive-learning platform: Elo/IRT
mastery estimation with read-time decay and a confidence function, a
prerequisite DAG with unlock gating and one-level mastery bleed, a
forced-review floor, a dedicated LLM taxonomy-generation path
(`bootstrap_first_skill` plus a whole-course generation mode), and a
proposal-and-review queue for new skills — observation counts, embedding
deduplication, an explicit promotion step. All of it had a real cost: a
"practice next skill" button and a mastery pill on the whiteboard, making the
engine a feature the student saw and interacted with, when `docs/PRODUCT.md`
never asked for one and §24 explicitly prefers qualitative insight over "one
opaque mastery score." The gate also actively hurt: a student whose ability
settled near 0.50 could never clear a fixed 0.60 unlock threshold and stayed
stuck on 3 of 15 topics in simulation, even though the estimate itself was
correct.

None of it is deferred — it's deleted. If gated prerequisites or a richer
estimator turn out to be genuinely needed later, that is a new design
exercise against the product as it exists then, not a resurrection of this
one.

---

## 11. Known gaps

- **Misconception tagging does not exist.** `TutorResponse` carries nothing
  finer than correct/incorrect/partial/uncertain, so there is no signal to
  build a "recurring mistake" observation from yet. Needs the tutor's
  existing model call to emit a tag per error (extending `TutorPlan`) — owned
  by the tutor path, not this one.
- **No qualitative observations feed (`PRODUCT.md` §24).** The rolling
  window and the derived profile are the substrate for "you've improved on
  substitution across your last 8 attempts"-style sentences, but nothing
  renders them yet.
- **The piggyback has no rate limit on topic creation.** A pathological
  model response could still mint several new topics per question. Bounded
  today only by `QuestionPlan.skills`'s max length (4) and
  `_MAX_SKILLS_PER_COURSE` (200).
- **Two persistence layers remain** (§47.1 in `ARCHITECTURE.md`). Documents,
  chunks and generated problems are raw sqlite3; everything the engine owns
  is SQLModel and FK-enforced. The boundary between them is not.

---

## 12. Verifying it

```bash
python -m pytest -q       # must pass twice in a row; never touches mentora.db
                           # or data/courses/*.json (see tests/conftest.py)
```

The dashboard at `GET /dev/dashboard` shows the whole topic list, per-student
accuracy, and buttons to drive the loop by hand.
