# LEARNING_ENGINE.md

What decides which problem a student sees next, and what tracks what they know.

Describes what is built. For product intent read `PRODUCT.md`; for the backend's
overall shape read `ARCHITECTURE.md`; for the tutor read `TUTOR_AGENT.md`.

| Concern | Module |
| --- | --- |
| Mastery math (pure, no I/O) | `services/mastery.py` |
| What to serve next, and the decayed read it needs | `services/selection.py` |
| Attempt ingestion and the student model | `services/student_model_service.py` |
| Which skills a problem exercises | `services/attribution.py` |
| Skills a model proposed but the course lacks | `services/proposals.py` |
| Taxonomy: build, validate, seed, merge | `services/taxonomy.py` |
| Cold-start skill generation | `services/skill_generation.py` |
| HTTP surface | `api/learning.py` |
| Dashboard, imports, proposal review | `api/dev.py`, `static/dashboard.html` |

---

## 1. The loop

```text
select_next()        which skill, at what difficulty
      |
search_course()      rank the course's chunks against the skill's
      |              retrieval query -> target document
      v
QuestionService      generate a problem grounded in that document
  .generate()        model also names the skills it thinks it exercises
      |
      +-- names an existing skill  -> attributed to it
      +-- names something new      -> recorded as a PROPOSAL, not attributed
      |
set_problem_skills() server-side attribution, plus the target difficulty
      |
      v
student works; POST /work sends the canvas
      |
tutor grades it     the server calls the tutor; the client never says
      |             whether the work was right
      v
record_attempt()    update mastery for the problem's recorded skills,
                    bleed onto prereqs, append to the ledger
```

Two closing edges matter.

**Attribution is written at generation time**, so when the work comes back the
engine knows what it actually served rather than trusting the client to say.

**Grading happens server-side.** `POST /work` takes the canvas and returns both
the tutor's response and the recorded attempt. Nothing the browser sends scores
the student's work.

---

## 2. Data model

Six SQLModel tables plus a raw-sqlite3 repository for documents, chunks and
generated problems. Same SQLite file (`mentora.db`, override `MENTORA_DB_PATH`).

**`Skill`** — one addressable unit of a course's taxonomy. Id is
course-prefixed and normalized (`calc1.derivatives.chain-rule`). Carries
`prereqs` (the DAG edges), `keywords` (retrieval vocabulary the textbook uses
that the name may not), `question_forms`, `difficulty_band`, and `origin`
(`seed` hand-authored, or `generated`).

**`SkillState`** — one student's estimate for one skill, keyed
`(student_id, skill_id)`. `mastery`, `attempts`, `correct_unassisted`, signed
`streak`, and `last_seen`. **`last_seen` is null until the skill is actually
practised**: a state created by prerequisite bleed has an estimate but no
practice to have decayed from.

**`Attempt`** — immutable. The ledger. Stored mastery is a function of this log
alone, which is what makes recomputation possible when a constant changes.
Unique on `(student_id, problem_id)`: one problem, one attempt.

**`ProblemSkill`** — which skills a problem exercises, `skill_id` a real
foreign key to `skill.id`. This is the table the attribution guarantee rests
on, which is why it lives beside `Skill` rather than in the repository.

**`SkillProposal`** — quarantine. A skill a model named that the course does
not have. Selection never reads it. See §4.

**`CourseTaxonomyVersion`** — content hash, so re-seeding is a no-op when the
course JSON hasn't changed.

---

## 3. Mastery

`services/mastery.py` is pure — no database, no I/O, no provider calls.

| Outcome | Score |
| --- | --- |
| Correct, no hints | 1.00 |
| Correct, one hint | 0.70 |
| Correct, multiple hints | 0.45 |
| Partial | 0.15 |
| Incorrect | 0.00 |

```python
expected = 1 / (1 + exp(-4.0 * (mastery - difficulty)))
mastery += learning_rate(attempts) * (score - expected)
alpha    = max(0.03, 0.50 / (1 + 0.35 * attempts))
```

**Why the residual and not the raw score.** Selection always serves difficulty
at or above current mastery (§5), so a student whose estimate has caught up to
their ability succeeds about half the time by construction. An EWMA toward raw
score chases a fixed point at `P(correct) == mastery` and gets trapped below
true ability. Moving toward the residual is difficulty-invariant at that point.

This is Elo's update rule with a decaying step size — worth naming, because the
literature on one-parameter IRT already answers most questions about it.

Bounds `[0.02, 0.98]`. Decay relaxes toward 0.5 with a 14-day halflife, applied
**on read only, never written back**. Confidence is `1 - exp(-attempts / 4)`.
10% of a mastery delta bleeds onto direct prerequisites, one level.

`ALPHA_FLOOR = 0.03` is empirical: at 0.15 the estimate never settled, staying a
bounded random walk oscillating 0.15–0.3 late in a skill's history. See
`scripts/simulate.py`.

---

## 4. Skills come from proposals, not from the read path

**Question generation may read the taxonomy and attribute to skills that exist.
It may not create one.**

This is the engine's most important constraint. Before it, every
`POST /next-problem` ran `build_taxonomy -> merge_generated`, so the skill graph
was an append-only log authored by a model on the read path and deduplicated by
slug equality on names the model chose. `chain-rule`, `the-chain-rule` and
`applying-the-chain-rule` were three skills with three mastery estimates, and
selection preferred all three over a skill the student was failing.

So: anything the model names that the course lacks is counted in
`SkillProposal`. Review (`POST /dev/courses/{id}/proposals/review`) then decides:

- fewer than `PROMOTION_MIN_OBSERVATIONS` distinct problems named it — stays
  pending. One model inventing a name once is noise.
- within `MERGE_SIMILARITY` cosine of an existing skill — **merged**. Later
  problems naming it attribute to the skill it matched.
- otherwise — **promoted** through the same `build_taxonomy` path as every
  other skill source.

Without an embedding provider the merge step is skipped and the report says so,
rather than silently pretending to deduplicate.

`bootstrap_first_skill` is the one exception: a course with documents but zero
skills has nothing to select and nothing to propose against, so it writes
exactly one skill, once, from the first few chunks.

---

## 5. Selection

`services/selection.py` is read-only.

**Unlock** — a skill is unlocked when every prerequisite has decayed mastery
≥ `0.60`. Locked skills are never served.

**Priority**

```python
attempts == 0:  W_COVERAGE                                   # 0.20
otherwise:      W_URGENCY * (1 - mastery) * confidence(n)    # 0.60
              + W_STALENESS * min(days_since / 7, 1)         # 0.25
              - W_RECENCY_PENALTY if recently served         # 0.40
```

Coverage and staleness are separate terms and that separation is the point.
Staleness once scored "never attempted" at a full 1.0 — a term meaning "decayed
since practice" — so an untouched skill scored 0.550 against 0.480 for a skill
the student was failing at 0.20 mastery. Novelty beat remediation, always.

Urgency is scaled by `confidence(attempts)`, so an estimate with no evidence
claims no urgency. Ties break toward lower `difficulty_band`, so a cold student
starts at the root of the graph.

**Forced review** — if the last 3 picks were all below mastery `0.70` and
something unlocked sits at or above it, selection forces a review pick and flags
`is_review`. Without it, urgency pins a struggling student to their weakest
material indefinitely.

**Difficulty** — `clamp(mastery + 0.15, 0.1, 0.9)`. Always slightly above the
estimate, which is why §3's residual update is necessary.

---

## 6. Attempt ingestion

`student_model_service.record_attempt()`.

1. **Already attempted?** Return the original attempt unchanged. The whiteboard
   posts on every "mark", so repeats are expected traffic; counting them would
   let ten marks on one correct canvas saturate mastery.
2. **Whose skills?** `ProblemSkill` rows win. The client's `expected_skills` is
   a hint, cross-checked and logged on mismatch. Problems with no rows fall back
   to the client's list, and that fallback is logged. Unknown skill ids raise
   `UnknownSkillError` → HTTP 400.
3. **Per skill** — update mastery, increment attempts, update the signed streak,
   stamp `last_seen`.
4. **Prerequisites** — bleed applied after every primary skill is updated, so a
   skill that is both target and prerequisite isn't counted against a stale
   mastery. Bleed-created states get a null `last_seen`.
5. **Ledger** — one immutable `Attempt`. Single commit.

---

## 7. API

Under `/api/courses/{course_id}`:

| Route | Does |
| --- | --- |
| `POST /work` | Grade a canvas and record the attempt. The product path. |
| `POST /next-problem` | select → ground → generate → attribute |
| `GET /next-problem-spec` | What the next problem should target. No model call. |
| `GET /student-model` | Decayed mastery per attempted skill, with confidence. |
| `GET /skills-overview` | Every skill, including untouched, with unlock state. |

`POST /work` records only when `mode=mark` and the tutor's status is not
`uncertain`. A hint is not a graded attempt, and `uncertain` means the tutor
never read the canvas.

`POST /next-problem` failure modes: 404 nothing unlocked / document missing ·
409 no indexed documents · 502 retrieval or generation failed · 503 retrieval
unconfigured · 504 generation timed out.

Dev-only, not in the OpenAPI schema:

| Route | Does |
| --- | --- |
| `GET /dev/dashboard` | Every skill, mastery, unlock state, proposals, synthetic attempts |
| `POST /dev/courses/{id}/attempts` | Record an attempt from a stated outcome |
| `GET|POST /dev/courses/{id}/proposals[/review]` | List and decide proposals |
| `POST /dev/courses/{id}/skills/import` | Paste a taxonomy batch |

`POST /dev/courses/{id}/attempts` takes `correct` from its caller, which is
exactly why it is not on the product API.

**Auth.** `MENTORA_API_KEY`, when set, is required on `/api` and `/dev`. It
authenticates the *caller*, not the student — `student_id` is still whatever the
request says, so any key holder can read or write any student's model. Per-student
identity needs a real user system.

---

## 8. Invariants

Each one names the test that enforces it. An invariant nothing checks is a wish.

| Invariant | Enforced by |
| --- | --- |
| Decay is applied on read, never written back | `test_student_model_service.py::test_get_student_model_applies_decay_on_read` |
| `mastery.py` has no I/O | `test_mastery.py` imports nothing else |
| Selection never writes | `test_selection.py` (in-memory session, no commits) |
| The client cannot attribute its own attempts | `test_closed_loop.py::test_select_generate_tag_grade_record_moves_the_selected_skill` |
| The client cannot score its own work | `test_work_api.py::test_difficulty_comes_from_generation_not_the_request` |
| One problem, one attempt | `test_student_model_service.py::test_reposting_the_same_problem_does_not_move_mastery_again` |
| Question generation never creates a skill | `test_question_service.py::test_generation_never_creates_a_skill` |
| A problem cannot be attributed to a skill that doesn't exist | `test_attribution.py::test_an_unknown_skill_is_dropped_with_a_warning_not_an_error`, plus the FK |
| Seed skills are read-only to generation | `test_taxonomy.py::test_merge_generated_never_overwrites_a_seed_skill` |
| Re-seeding never deletes generated skills | `test_taxonomy.py::test_seed_all_courses_reseed_never_deletes_generated_skills` |
| `SkillState` outlives taxonomy edits | `test_taxonomy.py::test_merge_generated_updates_existing_generated_skill_without_touching_state` |
| Remediation outranks novelty | `test_selection.py::test_a_failing_skill_outranks_an_untouched_one` |
| Bleed cannot reset a skill's decay clock | `test_selection.py::test_prereq_bleed_does_not_reset_a_skills_staleness` |
| A malformed skill batch never fails a problem request | `test_question_service.py::test_a_malformed_skill_batch_does_not_fail_the_problem_request` |

---

## 9. Known gaps

- **Misconception granularity does not exist.** It was removed, not deferred:
  the enum, the error reports and the per-skill counters were in the schema for
  months with zero rows in production, because the only client posted an empty
  error list. It comes back when the tutor's *existing* model call emits a tag
  per error (extending `TutorPlan`), not before.
- **`UNLOCK_THRESHOLD` is absolute, not relative.** A student whose true ability
  is ~0.50 can never clear 0.60, so they reach 3 of calc1's 15 skills and stay
  there. The estimate is correct; the gate is what's wrong. Probably it should
  be relative to the student, or the difficulty offset should adapt.
- **Hint-heavy students are misestimated.** Multi-hint correct scores 0.45
  regardless of ability, so `mastery` means something different for them
  (simulated MAE ~0.29 vs ~0.08). Defensible, but it is not the same quantity.
- **Prereq bleed is one level.** A deep chain doesn't propagate.
- **Selection is single-skill.** No integrative or multi-skill problems.
- **Two persistence layers remain.** Documents, chunks and generated problems
  are raw sqlite3; everything the learning engine owns is SQLModel. The
  learning-engine side is atomic and FK-enforced; the boundary between them
  is not.

---

## 10. Verifying it

```bash
python -m pytest -q                          # must pass twice in a row
python scripts/simulate.py                   # well-specified
python scripts/simulate.py --misspecified    # 3PL: guessing and slips
```

The default simulation samples outcomes from the same logistic family the
estimator assumes, so it tests the arithmetic and the plumbing but converges by
construction. `--misspecified` is the run that can actually fail — it adds a
guess floor and a slip ceiling the estimator does not model. Run both when
changing any constant in `mastery.py` or `selection.py`.

The dashboard at `GET /dev/dashboard` shows the whole taxonomy, per-student
mastery, pending proposals, and buttons to drive the loop by hand.
