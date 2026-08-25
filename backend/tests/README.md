# Backend test suite

```bash
python -m pytest -q                    # default: everything runnable
python -m pytest -q -m "not provider"  # no google-genai installed
RUN_LIVE_GEMINI=1 python -m pytest -q -m live -s
```

## Layout

### Tutor and question generation

| File | Covers | Needs |
| --- | --- | --- |
| `factories.py` | smallest-valid builders and the `StubWorkflow` port double | — |
| `test_tutor_schemas.py` | the wire contract: coordinates, the action union, strictness | pydantic |
| `test_tutor_policy.py` | the deterministic safety policy, as a pure function | pydantic |
| `test_tutor_service.py` | orchestration: id minting, workflow handoff, policy placement | pydantic |
| `test_tutor_api.py` | HTTP boundary: multipart, image sniffing, status mapping, leak guards | fastapi |
| `test_prompts.py` | mode policy distinctness and the allowed action set | — |
| `test_config.py` | one required credential | — |
| `test_tutor_workflow.py` | direct provider request, schema dialect, repair, failure translation | google-genai |
| `test_database.py` | additive SQLite schema, document replacement, problem grounding | sqlite3 |
| `test_documents_api.py` | document upload validation and listing | fastapi |
| `test_question_service.py` | bounded context selection and grounded persistence | pydantic |
| `test_question_workflow.py` | direct provider request, source-id validation, bounded repair | google-genai |
| `test_questions_api.py` | generated-problem HTTP contract and safe failures | fastapi |
| `test_embeddings.py` | chunk embedding; text stays in SQLite, never in metadata | — |
| `test_retrieval.py` | Pinecone ranking joined to canonical SQLite chunk text | — |
| `test_live_gemini.py` | opt-in real request | credentials |

### Learning engine

| File | Covers | Needs |
| --- | --- | --- |
| `test_mastery.py` | the pure update rules, as **properties** — bounds, monotonicity, decay | hypothesis |
| `test_taxonomy.py` | slug normalization, validation, cycle detection, seeding, `merge_generated` | — |
| `test_skill_generation.py` | cold-start bootstrap: one skill, one document, no documents | — |
| `test_taxonomy_workflow.py` | the taxonomy provider adapter's direct request and repair | google-genai |
| `test_selection.py` | unlock gating, priority, recency penalty, the forced-review floor | — |
| `test_student_model_service.py` | attribution, idempotency, mastery updates, prereq bleed, decay | — |
| `test_skills_overview.py` | the dashboard view: all skills, unlock state, seed defaults | — |
| `test_proposals.py` | the quarantine: recording, merging near-duplicates, promotion | — |
| `test_attribution.py` | which skills a problem counts toward; unknown ids dropped | — |
| `test_work_api.py` | server-side grading: the client scores nothing | fastapi |
| `test_closed_loop.py` | select → generate → tag → grade → record, end to end at the service layer | — |
| `test_next_problem_bootstrap.py` | the cold-start branch: bootstrap one skill, then retry selection | fastapi |
| `test_dev_api.py` | the dashboard page and the skills-import endpoint | fastapi |
| `test_proposals_api.py` | listing and reviewing proposals over HTTP | fastapi |

## Why the dependency column matters

Only the tutor, question, and taxonomy provider adapters may import
`google.genai`. Everything else — schemas, policy, services, database, and APIs
— remains testable without making a provider call.

That constraint is a design constraint, not a testing trick: it forces the
`TutorWorkflow` port to be declared by the service that consumes it rather than
by the adapter that implements it. `StubWorkflow` in `factories.py` is the only
double needed to exercise the entire request path.

## The two invariants worth knowing

**Uncertain work is never graded.** `WorkStatus.uncertain` means the canvas
could not be read. The policy strips every check and cross, and substitutes a
request for clarification. `test_tutor_policy.py` is the specification.

**Nothing from a provider reaches the client.** Provider messages can carry
credentials and prompt fragments. The API translates them into a status code
and a fixed string; `TestProviderFailure` asserts the original text never
appears in a response body.

---

# Testing the learning engine

For what the engine *is*, read `docs/LEARNING_ENGINE.md`. This section is how to
verify it.

```bash
python -m pytest -q tests/test_mastery.py tests/test_taxonomy.py \
  tests/test_selection.py tests/test_student_model_service.py \
  tests/test_skill_generation.py tests/test_skills_overview.py \
  tests/test_proposals.py tests/test_attribution.py tests/test_closed_loop.py \
  tests/test_work_api.py tests/test_next_problem_bootstrap.py tests/test_dev_api.py
```

**None of these spend a provider call.** Every one runs against an in-memory
SQLite database with a stubbed workflow, so the whole engine is exercisable with
no `GEMINI_API_KEY` set.

## The four layers, and what each one is for

The engine is tested in layers, deliberately. Each answers a question the layer
below it can't.

### 1. Is the math right? — `test_mastery.py`

`services/mastery.py` is pure — no DB, no I/O — so it is tested with
**hypothesis property tests** rather than examples. Properties, not cases:
mastery never escapes `[0.02, 0.98]` for any input; a perfect score never
decreases mastery and a zero score never increases it; the update is monotonic
in score; the learning rate is non-increasing in attempts; expected score is
exactly 0.5 at mastery/difficulty parity and falls as difficulty rises; decay is
the identity at zero elapsed days and moves toward 0.5 without overshooting.

This is the layer to extend when you change a constant, because a property that
holds for all inputs catches the case you wouldn't have thought to write.

### 2. Is one service right? — the unit tests

Each takes an in-memory SQLite session, builds the smallest graph that isolates
one rule, and asserts on it:

- **`test_selection.py`** — build a prereq DAG, set masteries, assert *which
  skill comes back*. Locked skills stay unserved; the recency penalty pushes off
  the just-served skill; three weak picks in a row force a review.
- **`test_student_model_service.py`** — attribution and idempotency. An attempt
  naming a skill outside the course 400s; re-posting the same problem returns
  the original attempt rather than moving mastery twice.
- **`test_proposals.py`** — the quarantine. A model-named skill the course lacks
  becomes a pending proposal, never a `Skill`; repeats accumulate on one row; a
  near-duplicate merges into the existing skill and a genuine gap is promoted.
- **`test_attribution.py`** — what a problem is attributed to, and that an id
  outside the taxonomy is dropped with a warning rather than stored.
- **`test_taxonomy.py`** — the largest file (25 tests) because it's the widest
  input surface: normalization is idempotent, cycles are caught with the path
  named, seed skills survive a re-seed, `merge_generated` blocks a seed
  collision and validates the *resulting* graph rather than just the batch.
- **`test_skills_overview.py`** — untouched skills appear at seed mastery rather
  than being omitted, and the view survives a failing `select_next`.

### 3. Does the loop close? — `test_closed_loop.py`

One test, and the most valuable in the suite.

It runs `select_next → render request → generate (stubbed) → set_problem_skills
→ grade → record_attempt` and asserts that mastery moved **for the skill
selection actually chose** — proving the server-side attribution path holds end
to end, not just that each half works alone.

If you break the `ProblemSkill` bridge, this is what catches it. Keep it
passing.

`test_work_api.py` covers the other half of the same guarantee: `POST /work`
grades server-side, takes difficulty from what generation recorded rather than
from the request, records nothing for a hint or an unreadable canvas, and
answers a repeated mark with the original attempt.

`test_next_problem_bootstrap.py` covers the same route's cold-start branch:
a course with documents but zero skills bootstraps exactly one skill and retries
selection. The route function is called directly with dependencies passed in and
`bootstrap_first_skill` stubbed, so there's still no provider call.

### 4. Does the *policy* work on a real student? — `scripts/simulate.py`

The layer unit tests structurally cannot reach.

A unit test asserts one decision in isolation. It cannot tell you whether
mastery converges to true ability **under the actual selection policy** — which
matters because selection always serves difficulty above current mastery, so the
estimator and the sequencer are coupled. Nor can it tell you whether some
reachable skill is quietly starved by the priority formula over hundreds of
attempts.

`simulate.py` drives the real `select_next()` and real `record_attempt()`
against the real 15-skill `calc1` taxonomy, samples outcomes from a hidden
true-ability model, and simulates the passage of time (batched sessions across
days, with gaps) so read-time decay is exercised the way it is for a student who
doesn't practice daily. Timestamps are corrected after each write rather than by
monkeypatching clocks, so the services under test run **unmodified**.

```bash
python scripts/simulate.py
# 5 archetypes x 3 trials x 600 attempts.
# Gates on: mastery MAE, rank correlation, skill starvation,
# selection stalls, and whether forced review ever fires.
# Exit 0 = all checks passed, 1 = a check failed, 2 = unknown archetype.

python scripts/simulate.py --seed 7 --trials 5
# Same suite, different seed, more trials. Run this FIRST when a
# threshold fails — it separates a real regression from sampling noise.

python scripts/simulate.py --archetype weak --attempts 800 --verbose
# Drill into one archetype with a per-skill table:
# depth, attempts, final mastery, hidden true ability.

python scripts/simulate.py --journey
# Narrate one novice-to-master run where true ability RISES with
# practice. The suite's thresholds don't apply; it passes only if
# every skill ends above the mastery bar.
```

Archetypes: `average`, `strong`, `weak`, `uneven_advanced_gap`, `hint_farmer`.

`uneven_advanced_gap` is the one that matters most for the review floor — it's
the only archetype that has mastered shallow skills to review while still
struggling on deep ones, so it's the only one where forced review *can* fire.
`weak` and `hint_farmer` have nothing above the review threshold at this attempt
budget, by construction.

**Run `simulate.py` whenever you change a constant in `mastery.py` or
`selection.py`.** The unit tests will still pass — they assert local behavior —
while convergence quietly degrades. This is the tool that justified lowering
`ALPHA_FLOOR` from 0.15 to 0.03 (late-stage oscillation down ~3–4×), and it's
the only thing that would have shown that.

## Testing by hand

Start the server and open **`http://localhost:8000/dev/dashboard`**.

Every skill in the course, with mastery bars, unlock state, origin, and buttons
to fire synthetic correct/partial/incorrect attempts against the currently
selected skill. It hits the same JSON APIs a real client would, so watching
mastery move there is watching the real loop run.

To test a **specific graph shape** without spending a model call, post a raw
taxonomy straight in:

```bash
curl -X POST localhost:8000/dev/courses/scratch/skills/import \
  -H 'content-type: application/json' \
  -d '{"skills":[{"id":"a","name":"A","description":"root",
        "difficulty_band":0.3,"prereqs":[]},
       {"id":"b","name":"B","description":"needs A",
        "difficulty_band":0.6,"prereqs":["a"]}]}'
```

It runs the same `build_taxonomy → merge_generated` path real generation uses,
so a pasted taxonomy is validated and merged exactly like a generated one. Seed
skills stay protected.

For a **cheap look at selection alone**, `GET /api/courses/{id}/next-problem-spec?student_id=x`
returns what the engine would target without generating anything — no model
call, no cost.

## Writing a new learning-engine test

Follow the existing shape:

```python
@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
```

In-memory, per-test, no shared state, no fixture file to keep in sync. Build the
smallest graph that isolates the rule you're testing — `test_selection.py`'s
`_skill()` helper is the pattern.

Two rules:

**Never let a learning-engine test import `google.genai`.** The taxonomy
workflow adapter is the only module in the engine allowed to, and
`test_taxonomy_workflow.py` is the only test that touches it. Everything else
stubs the `TaxonomyWorkflow` protocol.

**Assert on behavior, not on constants.** `assert chosen.id == "calc1.limits"`
survives a weight tweak; `assert priority == 0.62` does not, and re-encodes the
implementation into the test.
