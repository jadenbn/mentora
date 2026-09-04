# Backend test suite

```bash
python -m pytest -q                    # default: everything runnable
python -m pytest -q -m "not provider"  # skip live provider calls
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
| `test_tutor_workflow.py` | direct google-genai adapter: schema parsing, null stripping, repair, failure translation | google-genai |
| `test_database.py` | additive SQLite schema, document replacement, problem grounding | sqlite3 |
| `test_documents_api.py` | document upload validation and listing | fastapi |
| `test_question_workflow.py` | direct provider request, source-id validation, bounded repair | google-genai |
| `test_embeddings.py` | chunk embedding; text stays in SQLite, never in metadata | — |
| `test_retrieval.py` | Pinecone ranking joined to canonical SQLite chunk text | — |
| `test_live_gemini.py` | opt-in real request | credentials |

### Learning engine

The engine has no user-facing surface — it's consulted implicitly inside
question generation. These tests are all service-layer or dev-API; there is
no "next problem" route to test because there is no such route.

| File | Covers | Needs |
| --- | --- | --- |
| `test_taxonomy.py` | normalization, validation, `canonical_key`, seeding, `add_skills` | — |
| `test_selection.py` | topic priority: coverage vs weakness, recency, difficulty | — |
| `test_student_model_service.py` | the rolling accuracy window, idempotency, the overview query | — |
| `test_skills_overview.py` | the dashboard view: every topic, origin, recency | — |
| `test_attribution.py` | which skills a problem counts toward; unknown ids dropped | — |
| `test_question_service.py` | the piggyback: attribution, new-topic creation, name-similarity match | pydantic |
| `test_questions_api.py` | the one generation route: implicit topic pick, HTTP contract | fastapi |
| `test_work_api.py` | server-side grading: the client scores nothing | fastapi |
| `test_closed_loop.py` | pick topic → generate → tag → grade → record, end to end at the service layer | — |
| `test_dev_api.py` | the dashboard page and the skills-import endpoint | fastapi |

## Why the dependency column matters

Only the tutor and question provider adapters may import `google.genai`.
Everything else — schemas, policy, services, database, and APIs — must be
testable with pydantic, sqlite3, and fastapi alone, so the fast suite stays
fast and a provider SDK change cannot break tests that have nothing to do
with the provider.

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
python -m pytest -q tests/test_taxonomy.py tests/test_selection.py \
  tests/test_student_model_service.py tests/test_skills_overview.py \
  tests/test_attribution.py tests/test_question_service.py \
  tests/test_questions_api.py tests/test_closed_loop.py \
  tests/test_work_api.py tests/test_dev_api.py
```

**None of these spend a provider call.** Every one runs against an isolated
temporary SQLite database with a stubbed workflow, so the whole engine is
exercisable with no `GEMINI_API_KEY` set.

`conftest.py` points `MENTORA_DB_PATH` at a temp location before the first
`import app.*` and rebuilds the DB schemas around each test, so the suite
never touches `backend/mentora.db`. The course files under `data/courses`
need no such guard: they are read-only bootstrap data. **The
suite must pass twice in a row** — that is the check that catches a test
leaking state, which is how two fixture skills once ended up permanently in
the development database.

## What each layer answers

### Is one service right? — the unit tests

Each builds the smallest graph that isolates one rule and asserts on it:

- **`test_selection.py`** — set per-topic accuracy, assert *which topic comes
  back*. An untouched topic beats a mastered one (coverage); a topic the
  student is actively failing beats an untouched one (weakness beats
  coverage); the recency penalty pushes off the just-served topic; difficulty
  tracks accuracy once there's enough signal and defaults otherwise.
- **`test_student_model_service.py`** — the rolling window. A correct
  unassisted attempt scores 1.0, hinted lower, incorrect 0.0; the window caps
  at 8 outcomes while the attempt count keeps growing; re-posting the same
  problem returns the original attempt rather than moving accuracy twice.
- **`test_attribution.py`** — what a problem is attributed to, and that an id
  outside the topic list is dropped with a warning rather than stored.
- **`test_taxonomy.py`** — normalization is idempotent; `canonical_key`
  collapses reworded names to the same key; `add_skills` never overwrites an
  existing id; seeding skips a course that already has topics rather than
  overwriting what the model added.
- **`test_skills_overview.py`** — untouched topics appear with `accuracy:
  None` rather than being omitted; origin and recency are exposed for the
  dashboard.

### Does the piggyback actually create topics safely? — `test_question_service.py`

The widest surface in the suite, because it's where a model's free-text
output turns into schema. A named topic that already exists is attributed,
not duplicated; a genuinely new one is created *and lands in the skills
file*, not just the DB; the same topic named across repeated calls creates
exactly one row; a reworded name ("The Chain Rule" vs "chain rule") resolves
to the existing topic via `canonical_key`, not a duplicate; a seed topic is
never overwritten; a malformed batch (two entries colliding after
normalization) costs the model's own attribution, never the student's
problem.

### Does the loop close? — `test_closed_loop.py`

One test, and the most valuable in the suite.

It runs `pick_topic → generate (stubbed) → set_problem_skills → grade →
record_attempt` and asserts that accuracy moved **for the topic selection
actually chose** — proving the server-side attribution path holds end to end,
not just that each half works alone.

If you break the `ProblemSkill` bridge, this is what catches it. Keep it
passing.

`test_work_api.py` covers the other half of the same guarantee: `POST /work`
grades server-side, takes difficulty from what generation recorded rather than
from the request, records nothing for a hint or an unreadable canvas, and
answers a repeated mark with the original attempt.

`test_questions_api.py` covers the route itself: an empty request lets the
engine pick a topic; a typed request keeps the student's topic and only gets
a difficulty level appended; `required_skill_id` is set only in the
implicit-topic case.

## Testing by hand

Start the server and open **`http://localhost:8000/dev/dashboard`**.

Every topic in the course, with an accuracy bar, origin, and buttons to fire
synthetic correct/partial/incorrect attempts against a selected topic. It
hits the same JSON APIs a real client would.

To test a **specific topic list** without spending a model call, post a raw
batch straight into a course:

```bash
curl -X POST localhost:8000/dev/courses/scratch/skills/import \
  -H 'content-type: application/json' \
  -d '{"skills":[{"id":"a","name":"A","description":"topic a",
        "difficulty_band":0.3},
       {"id":"b","name":"B","description":"topic b",
        "difficulty_band":0.6}]}'
```

It runs the same `build_taxonomy → add_skills` path the piggyback uses, so
a pasted batch is validated and inserted exactly like a model-identified one.
An id that already exists is skipped, not overwritten.

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

In-memory, per-test, no shared state. Build the smallest graph that isolates
the rule you're testing — `test_selection.py`'s `_skill()`/`_state()` helpers
are the pattern.

**Assert on behavior, not on constants.** `assert topic.skill_id ==
"calc1.limits"` survives a weight tweak; `assert priority == 0.62` does not,
and re-encodes the implementation into the test.
