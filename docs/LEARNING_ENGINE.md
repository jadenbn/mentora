# LEARNING_ENGINE.md

The tutor's brain: a per-course topic list, and a per-student read of how
they're doing on each one. **It has no user interface.** No practice button,
no mastery readout, no "what do I know" screen. The student uploads a
document and asks for a question; the engine silently decides which topic and
how hard, tells the tutor how much scaffolding this student needs, and folds
the graded attempt back into what it knows.

For product intent read `PRODUCT.md`; for the backend's overall shape read
`ARCHITECTURE.md` §47; for the tutor read `TUTOR_AGENT.md`.

**Everything the engine owns lives in `backend/app/engine/`.** Import it
through the package (`from app.engine import pick_topic`), not by reaching
into modules — `app/engine/__init__.py` is the whole sanctioned surface, and
anything bypassing it is either a bug or a signal that surface should grow.

| Concern | Module |
| --- | --- |
| Score tiers, smoothing, difficulty wording (pure, no I/O) | `engine/accuracy.py` |
| Which topic to target next, and how hard | `engine/selection.py` |
| Course-wide accuracy, and what the tutor is told about the student | `engine/profile.py` |
| Attempt ingestion, and the dashboard's overview query | `engine/student_model_service.py` |
| Counting hints, so the client can't | `engine/hints.py` |
| Replaying the policy against synthetic students | `engine/simulation.py` |
| The engine's tables | `engine/models/` |
| Grading and the dashboard's HTTP surface | `engine/api/learning.py`, `engine/api/dev.py` |
| Request/response contracts | `engine/schemas.py` |

Two modules the engine depends on deliberately live **outside** it, because
question generation writes them and the engine only reads them:

| Concern | Module |
| --- | --- |
| Topic list: build, validate, seed, append | `services/taxonomy.py` |
| Which skills a problem exercises | `services/attribution.py` |
| The one generation route; the engine is consulted here | `api/questions.py` |

---

## 1. The loop

```text
student types a request, or leaves it blank
        |
        +-- blank -> pick_topic()      picks a topic + difficulty from this
        |                                student's per-topic estimate
        +-- typed -> get_profile()     offers a difficulty level from
        |                                course-wide accuracy; the student's
        |                                own request wins outright
        v
QuestionService.generate()    a grounded problem; the model also names the
                                skill(s) it thinks the question exercises
        |
        +-- names an existing topic -> attributed to it
        +-- names something new     -> minted through build_taxonomy (§5)
        v
set_problem_skills() + set_problem_difficulty() + mark_served()
        |
        v
student works; POST /work sends the canvas
        |
        v
get_learner_context()   the primary topic's estimate, attempt count, and
        |                 hints taken on this problem, rendered into the
        |                 tutor's prompt as one sentence (§8)
        v
        +-- mode=hint -> tutor answers at a depth set by that estimate;
        |                  the hint is counted, nothing is graded
        |
        +-- mode=mark -> tutor grades it, and may tag the error   the server
        |                  calls the tutor; the client never says whether
        v                  the work was right
apply_safety_policy() -> record_attempt()
        push the outcome (and any error tag) into the primary topic's window
```

**There is no "next problem" route.** Topic selection happens inside
`POST /questions/generate` — that is the entire mechanism behind "practice
next topic": an empty request is a valid one, and the engine fills in the
rest.

**Nothing the client sends scores the work.** The tutor decides the outcome,
generation decides the difficulty, and the server counts the hints. `/work`
has no field for any of the three.

**The engine reaches the model in exactly two places:** the generation call
(§5, §6), and the `<learner>` block handed to the tutor (§8). Everything else
in this document exists to compute what goes into those two crossings.

**At the generation crossing, the request outranks the engine.** Two separate
fields cross, and the split is the point:

| Field | Who authored it | Weight |
| --- | --- | --- |
| `question_request` | the student, when they typed one; the engine, when they didn't | **final say** |
| `preferred-difficulty` | always the engine | a preference, applied only where the request is silent on difficulty |

A typed request is passed through **verbatim** — trimmed, never augmented. It
used to have `(write at a moderate difficulty for this student)` appended to
it, which put the engine's preference inside the very string the prompt
presents as the student's own words: the model could not tell them apart, so
a student asking for something harder could be quietly overruled by their own
average. Sending the level in its own block is what makes "the student wins"
expressible at all. `prompts/question_generation.py` states the rule, and
`test_question_workflow.py` pins the level out of the request block.

When the request is blank the student expressed no preference, so the engine
authors the request too and is relied on for both topic and difficulty — the
same rule, with the engine on both sides of it.

---

## 2. Where topics come from, and what's still missing

Topics are **model-generated**. Nobody hand-authors a taxonomy: the
piggyback in question generation mints a topic whenever the model names
one the course lacks, and that is how a course's list grows.

The **database is the source of truth**. `add_skills()` inserts into `Skill`
and does nothing else — no file I/O on a request path.

`backend/data/courses/{course_id}.json` is **bootstrap data only**: a
starting list so a fresh course isn't empty. `seed_all_courses()` runs at
startup and skips any course that already has topics, so it never overwrites
or deletes what the model has added. Nothing writes back to those files.

### What still isn't shippable

- **There is no owner.** `Skill` is keyed on `course_id` alone, and a skill
  id is `{course_id}.{slug}`. Two users who both create a course about
  physics collide on the primary key. This is the real blocker for
  multi-user.
- **No `Course` table.** A course id is a bare string with no row behind it.
  It should be server-minted (`course_<uuid>`, never the user's typed
  subject name), with an indexed `owner_id`, a display `name`, and
  `created_at` — keeping the display name separate from the identifier is
  what stops two "Physics" courses being the same course.
- **`owner_id` scoping** on every taxonomy read, so a user only ever sees
  their own topics. Free text at first, exactly as `student_id` is today
  (§9), then wired to real accounts.
- **`Skill.course_id` should become a real foreign key** to `course.id`.
  This cannot be done with the additive-column reconciler in §3 — SQLite
  cannot `ALTER TABLE ADD CONSTRAINT`, so declaring it would enforce the FK
  on freshly created databases and silently skip every existing one. It
  needs a real migration tool.

---

## 3. Data model

Six SQLModel tables plus a raw-sqlite3 repository for documents, chunks and
generated problems. Same SQLite file (`mentora.db`, override
`MENTORA_DB_PATH`). The engine owns three of the six; the taxonomy and
attribution own the rest.

**`Skill`** (`models/skill.py`) — one topic in a course's flat list. Id is
course-prefixed and normalized (`calc1.derivatives.chain-rule`). No
prerequisite field — topics are flat. Carries `keywords` (retrieval
vocabulary), `question_forms` (§5), `difficulty_band`, and `origin` (`seed`
from the course's bootstrap file, or `generated` via the piggyback).

**`SkillState`** (`engine/models/skill_state.py`) — one student's rolling
window for one topic, keyed `(student_id, skill_id)`. `recent_outcomes`: the
most recent 8 scores, oldest first. `attempts` and `hints_used` count
everything, unbounded by the window. Two timestamps, and the difference
matters: `last_seen` is when the topic was last **graded** (drives
staleness), `last_served` is when it was last **put in front of the student**
(drives the recency penalty). A question that is generated and abandoned
moves `last_served` and nothing else.

**`Attempt`** (`engine/models/attempt.py`) — immutable. The ledger.
`engine/profile.py` derives the student profile from this alone. Unique on
`(student_id, problem_id)`: one problem, one attempt. Carries `error_tag`
(§8), nullable, written from the tutor's own reading and never by a client.

**`ProblemSkill`** (`models/problem_skill.py`) — which topics a problem
exercises, in declared order, `skill_id` a real foreign key to `skill.id`.
Order is load-bearing: the first is the problem's **primary** topic, and the
primary is the only one an outcome moves (§9).

**`HintUsage`** (`engine/models/hint_usage.py`) — how many hints a student
has taken on one problem, keyed `(student_id, problem_id)`. Counted
server-side on the way past, because a hint is worth 0.4 of a score and
whoever counts hints decides part of the grade.

**Table registration.** `SQLModel.metadata` only knows about a table whose
module has been imported, so `app/db.py` imports `app.engine.models` and
`app.models` together before `init_db()` runs. The dependency runs one way:
the engine imports the taxonomy's models, never the reverse.

**Schema changes.** There is no migration tool. `init_db()` runs
`create_all()` and then adds any column a model has gained since the database
was created — additive only, nullable or defaulted only, never a drop,
rename, or retype. It exists because `create_all()` silently skips tables
that already exist: adding `SkillState.last_served` left every dev database
on disk unable to answer a single query against that table, while the tests,
which build their schema fresh each run, saw nothing wrong. Anything beyond
adding a column still needs doing by hand.

---

## 4. Accuracy, not mastery

`engine/accuracy.py` is pure — no database, no I/O.

| Outcome | Score |
| --- | --- |
| Correct, no hints | 1.0 |
| Correct, with a hint | 0.6 |
| Partial | 0.3 |
| Incorrect | 0.0 |

**One definition, two scopes.** Per-topic accuracy is the mean of these
scores over a topic's recent window; course-wide accuracy (§7) is the mean of
the same scores over the whole ledger. Course-wide accuracy used to be
`correct / len(rows)` instead — a binary count in which a hint-assisted answer
weighed the same as an unassisted one and a partial weighed nothing — so
"accuracy" meant two incompatible things, and the weaker of the two was what
set the difficulty of every question a student typed a request for.

**Two numbers, and the gap between them is confidence.**

* `observed_accuracy(scores)` — the plain mean, `None` when there is nothing
  to average. Reporting only; the dashboard shows it.
* `estimated_accuracy(scores)` — the same mean shrunk toward
  `PRIOR_ACCURACY` (0.5) by `PRIOR_WEIGHT` (2.0) pseudo-observations. Always
  defined. **Everything that makes a decision reads this one.**

```python
estimate = (sum(scores) + PRIOR_WEIGHT * PRIOR_ACCURACY) / (len(scores) + PRIOR_WEIGHT)
```

So one wrong answer reads as 0.33, not 0.00, and eight wrong answers read as
0.10. This replaced a `has_signal(attempts >= 2)` threshold that gated
*difficulty* on having enough evidence but left *selection* acting on a
single data point: one bad attempt scored 0.60 on the priority formula and
outranked every topic in the course, including topics with eight attempts of
evidence behind them. Shrinkage handles both callers with one rule and no
cliff, and there is no "not enough data" branch left anywhere.

**`difficulty_bucket(difficulty)`** lives here too, and it is the lossiest
step in the system: it collapses a continuous target into one of three words
for a prompt — `introductory` below 0.4, `moderate` below 0.7, `challenging`
above. One definition, two callers: `api/questions.py` asks the generator for
one of these words, and `engine/simulation.py` buckets outcomes by the same
boundaries to check whether the word was honoured. A student estimated at
0.16 and one at 0.39 produce an identical prompt.

---

## 5. Topics come from the questions themselves

**Question generation may read the topic list and attribute to topics that
exist. It creates a new one only through the same validated path every other
topic source uses — never silently, and at most one per question.**

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
   and validator the bootstrap course JSON uses) and then
   `taxonomy.add_skills`, which inserts it. The database is the source of
   truth; nothing is written back to a file.

**Everything about a new topic is model-authored.** The generation prompt
asks for an id, name, description, `difficulty_band`, 3–12 `keywords`, and
1–3 `question_forms` — the shapes a question on this topic typically takes,
e.g. "evaluate a one-sided limit". `question_forms` feeds straight back into
the next prompt on that topic (§6), which is what stops the generator
reusing one worked example forever. Nothing in a taxonomy needs a human to
write it; a course can start empty and grow entirely from what the model
reads in the uploaded material.

`MAX_NEW_TOPICS_PER_QUESTION` is 1. A question genuinely covering more than
one unheard-of topic is a question that is not grounded in the material, and
one pathological response should not be able to mint four topics at once.
The cap is applied **after** validation, not before: truncating first would
let a malformed batch slip through by dropping the entry it collided with.

A malformed batch (e.g. two entries colliding after normalization) raises
`TaxonomyError` inside `_attribute_skills`. It's caught and logged there —
the taxonomy write is a side effect of generation, not the thing the student
asked for, so it never costs them the problem.

**Order.** When selection required a topic, that topic is inserted **first**,
ahead of whatever the model named. The first id is the primary, and the
primary is the one an outcome moves — so the topic the question was written
for is the topic the result counts toward.

**Cold start.** A course with no topics yet has nothing for `pick_topic` to
select; `POST /questions/generate` falls back to "write a question grounded
in this material" with no required topic and `PRIOR_ACCURACY` as the target
difficulty, and the model's own read seeds the first topics through the same
piggyback path. No separate bootstrap call exists.

---

## 6. Selection

`engine/selection.py`. `pick_topic` is read-only; `mark_served` is the one
writer, called from `api/questions.py` after a question actually exists.
Neither is a route of its own on the product API.

**Priority** — topics are flat, so there is no unlock gate:

```python
# no outcomes recorded yet (no state row, or an empty window):
base = W_COVERAGE                                          # 0.30
# otherwise, on the *smoothed* estimate:
base = W_WEAKNESS  * (1 - estimate)                        # 0.60
     + W_STALENESS * min(days_since_seen / cap, 1)         # 0.25

# applied either way:
priority = base - (W_RECENCY_PENALTY if recently served else 0)   # 0.40
```

Coverage and weakness are separate terms, and that separation is load-bearing.
An earlier, gated version of this scored "never attempted" staleness at a
full 1.0 — a term meaning "decayed since practice" — so an untouched topic
beat a topic the student was actively failing. Novelty beat remediation,
always. Ties break toward lower `difficulty_band`, so a cold student starts at
the easiest topic rather than wherever the query happened to order the rows.

**Where `W_COVERAGE` sits, and why it moved.** It is placed deliberately
between two weakness scores: above a topic the student is doing fine on
(estimate 0.58 → 0.25), below one they are struggling with (estimate 0.38 →
0.37). New material is served unless something already seen needs
remediation. At its original 0.20 it lost even to topics the student was
comfortable with, so the engine ground away at a handful of topics and the
rest of the course went unvisited. This is the one constant here that was not
set by hand — see §14.

**Staleness scales with strength.** The cap is
`STALENESS_BASE_DAYS * (1 + STALENESS_STRENGTH_STRETCH * estimate)` — seven
days for material the student has no grip on, about three weeks for material
they've got cold. A flat cap treated both the same, which is the opposite of
how retention works.

**Recency is about serving, not grading.** The penalty applies to the last
`RECENT_PICKS_WINDOW` (2) topics with the most recent `last_served`. It used
to read the attempt ledger, which meant a question the student read and
abandoned left no trace at all — so the engine re-served that topic forever,
to exactly the student who was bouncing off it. Reading `last_served` also
means secondary skills no longer dodge the penalty, and it removes a query.

**Difficulty** — an untouched topic is written at the `difficulty_band` its
taxonomy entry claims; after that, at the student's own estimate for it,
clamped to `[0.15, 0.85]`. There is no `mastery + offset` productive-struggle
formula — the estimate already sits where a residual estimator's fixed point
would. One consequence worth stating plainly: **a student who improves is
served harder questions at a similar score, rather than a rising score on the
same questions.** Growth shows up in the difficulty curve, not the accuracy
curve.

**An injectable clock.** `pick_topic`, `mark_served`, and `record_attempt`
each take an optional `now`, defaulting to the wall clock. Every production
caller leaves it unset; the simulator is the only caller that passes a
virtual timestamp, which is what lets §15 exercise staleness without a
multi-day run.

**Why no gate.** A gated design (unlock at mastery ≥ 0.60, served difficulty
always above the estimate) meant a student whose true ability settled around
0.50 could never clear the threshold — the estimate was correct, the gate
was wrong. An average student reached 3 of 15 topics under that design. A
flat pool has no such wall, and §15 is how that claim stays checkable.

---

## 7. Student profile

`engine/profile.py` — not a stored row. Computed on read from the `Attempt`
ledger: total attempts, and course-wide accuracy as the same smoothed mean of
the same score tiers §4 defines, one scope up. It can never drift from what
actually happened, and there's no migration if the definition changes.

`accuracy` is always defined — with no attempts it is exactly the prior — so
there is no "not enough signal yet" case for a caller to handle.

Used only when a student types their own question request. Their words decide
the topic, so the engine doesn't pick one and has no per-topic estimate to
read; the course-wide one offers a difficulty level instead — offers, not
imposes, since the student's request outranks it (§1).

---

## 8. What the tutor knows about the student

The engine's second crossing into a prompt. Until this existed, the tutor
graded and hinted knowing nothing about who it was talking to — the engine
personalized *what* was asked and not one thing about *how* the student was
taught.

**`get_learner_context()`** (`engine/profile.py`) reads the problem's primary
skill and returns a `LearnerContext`: the topic's name, its
`estimated_accuracy`, the attempt count, and how many hints the student has
already taken **on this problem**. It returns `None` when the skill id names
nothing in the course, and callers pass that straight through rather than
guessing.

Only `POST /work` builds one — it is the single path with a student identity.
The anonymous `POST /api/tutor/analyze` route passes `None`, and that
asymmetry is the point.

**It reaches the model as one sentence**, rendered by `_render_learner` in
`agents/tutor_workflow.py` into a `<learner>` block beside the problem and
the course excerpts:

```text
On {skill}, this student's estimated accuracy is {estimate:.2f} over
{attempts} attempt(s). They have taken {n} hint(s) on this problem so far.

This is the student's first attempt on {skill}.      <- attempts == 0
No student history is available for this topic.      <- no attributed skill
```

The system instruction tells the tutor to use it for **calibration, never for
correctness**: a pointer on a topic the student is strong on, something more
concrete on one they are weak on or where they have already taken hints, and
never to quote the number or the attempt count back to the student. That last
clause is what keeps the engine invisible — it shapes how the tutor talks,
and never becomes a score on the canvas (`PRODUCT.md` §24).

**Error tags.** `TutorPlan` carries an optional `error_tag` from a closed
five-value vocabulary in `schemas/tutor.py`: `sign_error`,
`dropped_constant`, `wrong_technique`, `algebra_slip`, `concept_gap`. The
vocabulary is deliberately small — a large one would be vaguer and would
never accumulate enough of any single tag to say anything.

`apply_safety_policy` clears the tag unless the status is `incorrect` or
`partial`. A tag on a correct answer, or on a canvas the tutor could not
read, is model noise, and the policy is the one place that cannot be routed
around. What survives is stored on `Attempt.error_tag`.

**Nothing reads the tags yet, and that is deliberate.** A per-student rollup
only becomes useful after weeks of real grading, so the signal has to start
accumulating before the feature that consumes it can exist. See §16.

---

## 9. Attempt ingestion

`student_model_service.record_attempt()`.

1. **Already attempted?** Return the original attempt unchanged. The
   whiteboard posts on every "mark", so repeats are expected traffic;
   counting them again would let ten marks on one canvas all count toward
   accuracy.
2. **Whose skills?** `ProblemSkill` rows win, in order. The client's
   `expected_skills` is a hint, cross-checked and logged on mismatch.
   Unknown skill ids raise `UnknownSkillError` → HTTP 400.
3. **Credit goes to the primary topic only.** The first declared skill takes
   the outcome: its window gets the score, its `attempts` increments, its
   `last_seen` is stamped. The rest stay on the ledger as attribution and
   move nothing. One outcome cannot say which of four skills a wrong answer
   failed at — pushing the same score into all of them blurred every topic on
   the problem *and* inflated the attempt counts confidence is built from, so
   a student who nailed the chain rule and fumbled the arithmetic had both
   topics marked wrong.
4. **Ledger** — one immutable `Attempt`, recording every declared skill and
   any surviving `error_tag`. Single commit.

`updated_skills` in the response reports the primary's **estimate** after the
attempt — what selection will act on next — not the raw score.

No prerequisite bleed: there's no prerequisite graph to bleed onto.

---

## 10. API

Under `/api/courses/{course_id}`:

| Route | Does |
| --- | --- |
| `POST /questions/generate` | The one generation path. Engine consulted implicitly (§1). |
| `POST /work` | Grade a canvas and record the attempt, or answer a hint and count it. Builds the learner context (§8). |
| `GET /skills-overview` | Every topic with this student's observed accuracy and estimate. Dev dashboard only. |

`POST /work` records an attempt only when `mode=mark` and the tutor's status
is not `uncertain`. A hint is not a graded attempt — it is counted and
nothing else — and `uncertain` means the tutor never read the canvas.

Dev-only, not in the OpenAPI schema:

| Route | Does |
| --- | --- |
| `GET /dev/dashboard` | Every topic, estimate, observed accuracy, origin, and synthetic attempts. |
| `GET /dev/courses/{id}/next-topic` | What `pick_topic` would choose right now. Read-only — does not stamp `last_served`. |
| `POST /dev/courses/{id}/simulate` | Replay the policy against synthetic students (§15). |
| `POST /dev/courses/{id}/attempts` | Record an attempt from a stated outcome, and stamp `last_served` — on the real path a topic is always served before it is marked. |
| `POST /dev/courses/{id}/skills/import` | Paste a topic batch straight into a course. |

`POST /dev/courses/{id}/attempts` takes `correct` and `hints_used` from its
caller, which is exactly why it is not on the product API.

**Auth.** `MENTORA_API_KEY`, when set, is required on `/api` and `/dev`. It
authenticates the *caller*, not the student — `student_id` is still whatever
the request says, so any key holder can read or write any student's model.
Per-student identity needs a real user system, and lands with the `owner_id`
work in §2.

---

## 11. Invariants

| Invariant | Enforced by |
| --- | --- |
| Question generation never creates a topic outside `build_taxonomy` | `test_question_service.py::test_generation_identifies_a_new_topic_via_the_piggyback` |
| A differently-worded name resolves to the same topic, not a duplicate | `test_question_service.py::test_a_differently_worded_name_resolves_to_the_same_topic` |
| A typed request reaches the generator verbatim, never augmented | `test_questions_api.py::test_a_typed_request_reaches_the_generator_untouched` |
| The engine's difficulty is offered beside the request, never inside it | `test_questions_api.py::test_the_engine_offers_a_difficulty_beside_a_typed_request`, `test_question_workflow.py::test_direct_request_sends_grounding_and_schema_configuration` |
| A malformed skill batch never fails the problem request | `test_question_service.py::test_a_malformed_skill_batch_does_not_fail_the_problem_request` |
| A problem cannot be attributed to a topic that doesn't exist | `test_attribution.py`, plus the FK on `ProblemSkill.skill_id` |
| Seed topics are never overwritten by the piggyback | `test_question_service.py::test_generation_never_overwrites_a_seed_skill` |
| The client cannot score its own work, outcome or hints | `test_work_api.py::test_a_correct_mark_records_an_attempt_the_client_never_scored`, `::test_a_hint_is_counted_by_the_server_and_lowers_the_later_score` |
| One problem, one attempt | `test_student_model_service.py::test_reposting_the_same_problem_does_not_move_accuracy_again` |
| Only the primary topic takes an outcome | `test_student_model_service.py::test_only_the_primary_skill_takes_the_outcome` |
| The recent-outcomes window is capped, attempt count is not | `test_student_model_service.py::test_the_window_caps_at_eight_outcomes` |
| One attempt never outweighs eight | `test_accuracy.py::test_evidence_outweighs_the_prior_as_it_accumulates`, `test_selection.py::test_one_bad_attempt_does_not_outrank_a_topic_with_real_evidence` |
| Hints count against accuracy at both scopes | `test_accuracy.py::test_a_hinted_correct_answer_is_worth_less_than_an_unassisted_one`, `test_profile.py::test_hints_count_against_course_wide_accuracy` |
| Coverage and weakness are separate priority terms | `test_selection.py::test_a_failing_topic_outranks_an_untouched_one` |
| An abandoned question still counts as served | `test_selection.py::test_an_abandoned_question_still_counts_as_served` |
| Staleness actually changes a pick, under an explicit clock | `test_selection.py::test_a_topic_gone_stale_under_an_explicit_clock_outranks_a_freshly_seen_one` |
| The tutor is told the student's standing on the primary topic | `test_work_api.py::test_the_tutor_receives_a_learner_context_for_an_attributed_problem` |
| The anonymous tutor route is told nothing about the student | `test_tutor_service.py::test_no_learner_context_reaches_the_workflow_by_default` |
| The learner context reaches the prompt, or says it is absent | `test_tutor_workflow.py::test_a_learner_context_reaches_the_prompt`, `::test_with_no_learner_context_the_prompt_says_so` |
| An error tag survives only on incorrect or partial work | `test_tutor_policy.py::TestErrorTag` (5 cases) |
| The error-tag vocabulary stays closed | `test_tutor_schemas.py::test_error_tag_is_a_small_closed_vocabulary` |
| A tag the tutor set is stored on the attempt | `test_work_api.py::test_the_tutors_error_tag_is_stored_on_the_attempt` |
| Looking at the next pick does not change it | `test_dev_api.py::test_next_topic_previews_the_pick_without_serving_it` |
| The simulator never writes to the real database | `test_simulation.py::test_the_simulation_never_writes_to_the_real_database` |
| A model's new column reaches a database that predates it | `test_db_schema.py::test_a_column_added_to_a_model_is_added_to_an_existing_table` |

---

## 12. Tuning constants

Every number the policy turns on, in one place. Most were set by hand; the
column that says so is the point.

| Constant | Value | Where | How it was chosen |
| --- | --- | --- | --- |
| `RECENT_WINDOW` | 8 | `engine/models/skill_state.py` | By hand. Long enough to average noise, short enough that old outcomes age out without a decay function. |
| `PRIOR_ACCURACY` | 0.5 | `engine/accuracy.py` | By hand. Where a topic sits with no evidence. |
| `PRIOR_WEIGHT` | 2.0 | `engine/accuracy.py` | By hand. The third real attempt is where the student's record starts to outweigh the prior. |
| `W_COVERAGE` | 0.30 | `engine/selection.py` | **Measured** (§15). At 0.20 an average student reached 6 of 15 topics in 30 questions. |
| `W_WEAKNESS` | 0.60 | `engine/selection.py` | By hand. The dominant term: remediation is the point. |
| `W_STALENESS` | 0.25 | `engine/selection.py` | By hand. |
| `W_RECENCY_PENALTY` | 0.40 | `engine/selection.py` | By hand. Large enough to beat any single-term difference. |
| `STALENESS_BASE_DAYS` | 7.0 | `engine/selection.py` | By hand. |
| `STALENESS_STRENGTH_STRETCH` | 2.0 | `engine/selection.py` | By hand. Strong material gets ~3× the grace of weak material. |
| `DIFFICULTY_FLOOR` / `CEIL` | 0.15 / 0.85 | `engine/selection.py` | By hand. Outside this, a question stops being worth writing. |
| `RECENT_PICKS_WINDOW` | 2 | `engine/selection.py` | By hand. |
| `MAX_ACTIONS` | 12 | `services/tutor_policy.py` | By hand. A whiteboard buried in annotations is worse feedback than none. |
| `MAX_NEW_TOPICS_PER_QUESTION` | 1 | `services/question_service.py` | By hand. |
| `RETRIEVAL_TOP_K` | 12 | `services/question_service.py` | By hand. Chunks retrieved when a document is too large to send whole. |
| `_MAX_SKILLS_PER_COURSE` | 200 | `services/taxonomy.py` | By hand. A generator producing more has malfunctioned. |

Simulator-only knobs (`engine/simulation.py`) describe the synthetic learner,
not the policy: `DIFFICULTY_EFFECT` 0.6, `LEARNING_RATE` 0.04, `PARTIAL_BAND`
0.15, and `attempt_interval_days` (default 0.0, see §15).

Changing any of them is a `POST /dev/courses/{id}/simulate` away from being
checked rather than argued about.

---

## 13. What was cut, and why

An earlier version of this engine was an adaptive-learning platform: Elo/IRT
mastery estimation with read-time decay and a confidence function, a
prerequisite DAG with unlock gating and one-level mastery bleed, a
forced-review floor, a dedicated LLM taxonomy-generation path, and a
proposal-and-review queue for new skills. All of it had a real cost: a
"practice next skill" button and a mastery pill on the whiteboard, making the
engine a feature the student saw and interacted with, when `docs/PRODUCT.md`
never asked for one and §24 explicitly prefers qualitative insight over "one
opaque mastery score." The gate also actively hurt: a student whose ability
settled near 0.50 could never clear a fixed 0.60 unlock threshold and stayed
stuck on 3 of 15 topics, even though the estimate itself was correct.

Cut since, smaller and for the same reason — a mechanism that existed but
didn't earn its place:

* **`has_signal` / `MIN_ATTEMPTS_FOR_SIGNAL`** — a threshold that half the
  callers honoured. Replaced by smoothing, which has no cliff (§4).
* **`Attempt.total_time_ms`** — collected on the schema, never populated by
  `/work`, never read. Deleted rather than left looking live.
* **Client-side hint counting** — the browser's `hintCount` ref, the
  `hints_used` form field, and the parameter chain that carried it. The
  server counts hints now, so the client code that did was dead weight.
* **Course-wide accuracy as a binary count** — see §4.
* **Recency read from the attempt ledger** — replaced by `last_served`,
  which is both more correct and one query cheaper (§6).
* **A duplicated difficulty-wording helper** — `_level_word` in
  `api/questions.py` and `_bucket` in the simulator were byte-identical.
  Collapsed into `accuracy.difficulty_bucket`, so the simulator now measures
  the same boundaries generation asks against.

Three things worth continuing to resist:

1. **A prerequisite DAG with unlock gates.** The failure was not the graph,
   it was the gate. If prerequisites return, they should bias priority, never
   withhold a topic.
2. **A mastery score on the whiteboard.** The engine's invisibility is a
   product decision, not an unfinished feature.
3. **A richer estimator (IRT, Bayesian knowledge tracing) before the
   item-quality problem in §16 is solved.** A better estimator fed by
   unvalidated items produces more confident wrong answers, which is strictly
   worse than the honest, shrunk-toward-0.5 estimate that exists now.

None of the cut work is deferred — it's deleted. If any of it turns out to be
genuinely needed later, that is a new design exercise against the product as
it exists then, not a resurrection of this one.

---

## 14. Layout

The engine is one directory, and the boundary is enforced by convention plus
review rather than by the language:

```text
backend/app/engine/
    __init__.py                 the public surface — import from here
    accuracy.py                 pure scoring, smoothing, difficulty wording
    selection.py                pick_topic / mark_served
    profile.py                  course-wide accuracy + LearnerContext
    student_model_service.py    record_attempt + skills overview
    hints.py                    server-side hint counting
    simulation.py               policy replay
    models/                     Attempt, SkillState, HintUsage
    api/                        learning.py (product), dev.py (dashboard)
    schemas.py                  request/response contracts
    static/dashboard.html       the dev dashboard page
```

External consumers, in full: `api/questions.py` (topic + difficulty at
generation time), `services/tutor_service.py` and `agents/tutor_workflow.py`
(`LearnerContext` only), and `bootstrap.py` (mounts the two routers). Every
one of them imports from `app.engine`, not from a module inside it.

`services/taxonomy.py` and `services/attribution.py` stay outside on purpose:
they are the bridge between question generation and the engine — generation
writes them, the engine reads them — and they are the two modules the §2
migration will rewrite.

---

## 15. Verifying it

Three surfaces, and they answer different questions.

```bash
python -m pytest -q       # 285 passed, 2 skipped; must pass twice in a row.
                          # Never touches mentora.db or data/courses/*.json
                          # (see tests/conftest.py).
```

Tests prove the **mechanism** is correct: a score lands in the right window,
an unknown skill is refused, a repeat mark doesn't count twice.

`GET /dev/dashboard` shows the **state**: the whole topic list, each topic's
estimate beside its observed accuracy (the gap between the two columns is the
confidence), when it was last served, and buttons to drive the loop by hand.
"Preview next topic" runs the real `pick_topic` without serving it, so you can
watch selection change as you record synthetic attempts.

`POST /dev/courses/{id}/simulate`, on the same page, measures the **policy** —
the question pytest cannot answer, and the reason the constants in §12 were
guesses for as long as they were. It replays the real
`pick_topic → mark_served → record_attempt` loop over synthetic students
against a throwaway in-memory database, so there is no second copy of the
policy to drift from the first and no synthetic student ever reaches
`mentora.db`. What to read:

| Metric | Should be |
| --- | --- |
| `coverage` | High. A flat pool has no wall; a low number means selection is grinding on a few topics. |
| `difficulty_early` → `difficulty_late` | Rising. This is where growth shows up (§6). |
| `score_early` → `score_late` | Roughly level. A collapse means students are being pushed past what they can do. |
| `repeat_rate` | Near zero. The recency penalty exists for this. |
| `calibration` | Falling across introductory → moderate → challenging. Read the caveat below before trusting it. |

`tests/test_simulation.py` pins these as directional assertions, so a
regression in the policy fails the suite rather than waiting to be noticed.
The learner model is crude and the absolute numbers mean little; the signal
is how they *move* when a constant changes.

**The calibration metric is confounded, and the test says so.** Difficulty is
*defined* as the student's own estimate for the topic (§6), so a
"challenging" question is by construction one served on a topic the student
is already good at — the metric regresses score against a variable derived
from the same quantity that predicts score. Asserting a strict ordering at
one hardcoded seed is therefore closer to a coin flip than a measurement: on
the suite's synthetic 15-topic course 1 seed in 11 inverts outright, and on
the real `calc1` taxonomy an earlier review found 2 in 5.
`test_harder_questions_produce_lower_scores_on_average_across_seeds` now
sweeps seeds 1–11 and asserts on the average, which does not remove the
confound but does answer a narrower honest question: does the intended
direction dominate. It does — 0.60 → 0.54 → 0.34 across the three buckets.
The real fix is for generation to report the difficulty it believes it wrote
at, and to calibrate against the delta from the requested target.

**Spacing is opt-in.** By default every simulated attempt happens at the same
virtual instant, matching every measurement this module has historically
reported. Passing `attempt_interval_days` advances a jittered virtual clock
between attempts, which is the only way `STALENESS_BASE_DAYS` and
`STALENESS_STRENGTH_STRETCH` get exercised at all. Turning it on **lowers
coverage** — once a topic's staleness saturates, a stale-but-known topic can
outscore one the student has never touched, because `W_STALENESS` (0.25) sits
above the `W_COVERAGE` (0.30) baseline once weakness is low. That is a real
interaction between the constants, not a bug in the clock;
`test_a_realistic_pace_lets_staleness_compete_with_coverage` pins it so it
stays visible, and retuning the weights for spaced practice is open work.

---

## 16. Known gaps

- **The taxonomy is a JSON prototype.** Six specific failure modes and the
  planned migration are in §2. This is the largest structural gap, and it
  blocks the multi-user product entirely.
- **No item-quality signal.** A generated question that is ambiguous or
  simply wrong gets the student marked incorrect, and the engine records a
  genuine weakness on that topic. There is no per-item statistic, no way to
  flag or retire a bad item, and no feedback into generation. This is the
  failure mode that makes an auto-generated-content engine drift, and it is
  the largest *behavioural* gap on this list. The cheapest first move is a
  student-facing "this question is wrong" affordance, which converts the
  worst case — the student is right, the tutor is wrong, the engine records a
  weakness — from silent corruption into labelled data.
- **Nothing reads the error tags yet.** §8 stores them; no per-student rollup
  exists, so "sign again — that's the third time this week" is not possible
  yet. Deliberate, but it is a gap until something consumes it.
- **No qualitative observations feed (`PRODUCT.md` §24).** The rolling
  window and the derived profile are the substrate for "you've improved on
  substitution across your last 8 attempts"-style sentences, but nothing
  renders them yet.
- **Nothing verifies the difficulty word landed.** The engine asks for
  `challenging` and records the float it meant; no signal comes back saying
  what the generator actually wrote. See the calibration caveat in §15.
- **Topics can be minted but never merged, renamed, or retired.**
  `add_skills` only inserts. `canonical_key` catches re-wordings and
  `MAX_NEW_TOPICS_PER_QUESTION` caps the rate, but over months the taxonomy
  can still fragment with no remedy. If a skill does go missing,
  `engine/api/learning.py` catches the resulting `UnknownSkillError` and the
  accuracy update is lost; orphaned `SkillState` rows are never cleaned up.
- **`Attempt.difficulty` is recorded, not scored against.** A correct answer
  at 0.85 and one at 0.15 count identically. It is kept as provenance — what
  generation asked for — and as the guard that a problem came through the
  engine at all.
- **Identity is per-caller, not per-student.** See §10. Lands with the
  `owner_id` work in §2.
- **Concurrent marks on one student can drop an outcome.**
  `recent_outcomes` is a read-modify-write on a JSON column over SQLite. Fine
  at demo scale, stated here rather than left as an oversight.
- **`attempt.total_time_ms` is still a column on existing databases.** The
  field was removed from the model, and the reconciler in §3 only ever adds
  columns, so a database created before the change keeps an unused nullable
  column. Harmless; dropping it is a hand job on a dev file.
- **Two persistence layers remain** (§47.1 in `ARCHITECTURE.md`). Documents,
  chunks and generated problems are raw sqlite3; everything the engine owns
  is SQLModel and FK-enforced. The boundary between them is not.
