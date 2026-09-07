# Mentora

Mentora is a persistent AI whiteboard tutor. A student works by hand on a
tldraw canvas, then asks for Mark, Hint, Explain, or I'm Stuck — or asks the
question out loud. The backend sends the canvas, and any spoken question,
through a direct async Gemini SDK call and returns validated spatial actions
for the whiteboard renderer to draw. A learning engine sits behind question
generation: it picks what topic a student practices next and how hard,
without any interface of its own — see `docs/LEARNING_ENGINE.md`.

## Repository

- `frontend/`: Next.js, React, and tldraw whiteboard UI.
- `backend/`: FastAPI tutor service and course ingestion.
- `docs/PRODUCT.md`: authoritative product behavior.
- `docs/ARCHITECTURE.md`: system boundaries and shared contracts.
- `docs/TUTOR_AGENT.md`: the tutor API contract.
- `docs/LEARNING_ENGINE.md`: the topic-selection and student-model engine behind question generation.

## Setup on a new machine

Four things are gitignored and must be recreated: `backend/.venv`,
`backend/.env`, `frontend/.env.local`, and `frontend/node_modules`.

### Backend

Needs Python 3.11 or newer (`asyncio.timeout`).

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then add Gemini, OpenAI, and Pinecone credentials
.venv/bin/uvicorn app.main:app --reload --port 8000
```

`GEMINI_API_KEY` powers tutoring, question generation, and voice — and
nothing else needs configuring for those. Large-document indexing and
retrieval additionally require `OPENAI_API_KEY`, `PINECONE_API_KEY`, and
`PINECONE_INDEX_NAME`. Create that Pinecone index with 1,536 dimensions and
cosine similarity for `text-embedding-3-small`.
Canonical document chunks and generated-problem grounding stay in
`backend/mentora.db`, alongside courses, spaces, and the learning engine's own
tables; Pinecone stores only embeddings and chunk identifiers.
Override SQLite with `MENTORA_DB_PATH` and the default 40,000-character
full-context cutoff with `QUESTION_FULL_CONTEXT_MAX_CHARS`.

Check it came up configured:

```bash
curl -s localhost:8000/health     # reports tutor and course_indexing readiness
```

### Frontend

```bash
cd frontend
bun install
cp .env.example .env.local        # already points at localhost:8000
bun dev
```

Then open `localhost:3000` → My courses → a course. From there, either upload
a material → describe the question you want → Generate question → draw beside
the problem, or skip straight to New space → draw. Either way, open the tutor
control on the right edge and pick an action, or the microphone beside them. A
spoken question is transcribed and shown to you first: edit anything it
misheard, then tap Ask to send it to the tutor.

The optional live seed check uploads the checked-in chain-rule lecture, writes
its text to SQLite and embeddings to Pinecone, and verifies retrieval:

```bash
cd backend && PYTHONPATH=. .venv/bin/python scripts/seed_course.py --reset
```

### From a phone or tablet on the same network

The frontend points itself at whatever host served the page, so the API base
URL needs no configuration. Two things do: the backend must accept that origin
and listen beyond loopback, and Next must allow the origin to reach its dev
server.

```bash
# backend, in place of the command above
CORS_ALLOW_ORIGINS=http://localhost:3000,http://YOUR-IP:3000 \
  .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# frontend
ALLOWED_DEV_ORIGINS=YOUR-IP bun dev --hostname 0.0.0.0
```

`ALLOWED_DEV_ORIGINS` is a comma-separated list of hostnames; without it Next
blocks the tablet's cross-origin requests for dev-only assets. It can live in
`frontend/.env.local` instead of the command line.

`--host 0.0.0.0` exposes the API to your whole network, and on a machine with
a public address, to the internet. There is no authentication and every
request spends Gemini quota, so only do this on a trusted network and stop the
server afterwards.

#### Voice needs HTTPS there

The whiteboard and the tutor buttons work over `http://YOUR-IP:3000`, but the
microphone will not. `getUserMedia` is only available in a secure context, and
a plain-HTTP LAN address is not one — browsers exempt `localhost` only. On the
tablet the microphone button reports "Voice needs a secure (https) connection"
rather than recording.

To exercise voice on a real device, serve the frontend over HTTPS from a URL
the tablet trusts: a tunnel that terminates TLS for you, a deployed staging
build, or a locally-issued certificate whose CA is installed on the tablet.
Point `NEXT_PUBLIC_API_BASE_URL` at an HTTPS backend as well — a secure page
cannot call a plain-HTTP API. Do not disable the browser's secure-context
requirement to get around this.

## The tutor endpoint

`POST /api/tutor/analyze`, multipart form data:

```text
course_id          course and grounded-problem scope
mode               mark | hint | explain | stuck
canvas_image       PNG, JPEG, or WebP; maximum 10 MB
prior_annotations  JSON array of normalized bounds; defaults to []
problem_context    optional generated problem, as JSON
transcript         optional spoken question; maximum 1000 characters
```

Speech reaches it through `POST /api/voice/transcribe`, which takes one WAV
recording (16 kHz mono, maximum 5 MiB) and returns the words. It uses a
dedicated speech-to-text model, `GEMINI_TRANSCRIPTION_MODEL` (default
`gemini-3.5-transcribe`), and the recording it uploads is deleted again within
the request. The transcript goes to the student for confirmation, not straight
to the tutor. See `docs/TUTOR_AGENT.md`.

A skill-attributed problem instead goes through `POST
/api/courses/{course_id}/work` — the learning engine's own route, which
grades and records the attempt server-side rather than the client scoring
itself. See `docs/LEARNING_ENGINE.md`.

Full contract in `docs/TUTOR_AGENT.md`.

## Tests

```bash
cd backend  && .venv/bin/python -m pytest -q -m "not live"    # 389, no provider calls
cd frontend && bun run test
```

The opt-in live check spends one real Gemini request:

```bash
cd backend && RUN_LIVE_GEMINI=1 .venv/bin/python -m pytest -q -m live -s
```

## Team workstreams

- Jaden: whiteboard and frontend integration.
- Andre: AI/Vision and backend tutor APIs.
- Korey: course context ingestion and retrieval.
- Ren: question generation and learning engine.
