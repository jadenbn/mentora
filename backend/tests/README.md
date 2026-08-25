# Backend test suite

```bash
.venv/bin/python -m pytest -q                    # default: everything runnable
.venv/bin/python -m pytest -q -m "not provider"  # skip live provider calls
RUN_LIVE_GEMINI=1 .venv/bin/python -m pytest -q -m live -s
```

## Layout

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
| `test_live_gemini.py` | opt-in real request | credentials |

## Why the dependency column matters

Only provider adapters may import `google-genai`. Everything else — schemas,
policy, service, API — must be testable with pydantic and fastapi alone, so the
fast suite stays fast and a provider SDK change cannot break tests that have
nothing to do with the provider.

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
