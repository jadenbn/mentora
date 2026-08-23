# Mentora

Mentora is a persistent AI whiteboard tutor. A student works by hand on a
tldraw canvas, then asks for Mark, Hint, Explain, or I'm Stuck. The backend
sends the canvas to a multimodal Gemini agent and returns validated spatial
actions for the whiteboard renderer to draw.

## Repository

- `frontend/`: Next.js, React, and tldraw whiteboard UI.
- `backend/`: FastAPI tutor service and course ingestion.
- `docs/PRODUCT.md`: authoritative product behavior.
- `docs/ARCHITECTURE.md`: system boundaries and shared contracts.
- `docs/TUTOR_AGENT.md`: the tutor API contract.

## Setup on a new machine

Four things are gitignored and must be recreated: `backend/.venv`,
`backend/.env`, `frontend/.env.local`, and `frontend/node_modules`.

### Backend

Needs Python 3.11 or newer (`asyncio.timeout`).

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then paste a real GEMINI_API_KEY into it
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Only `GEMINI_API_KEY` is required. The OpenAI and Pinecone keys in
`.env.example` are for course ingestion, which the tutor does not use — see
"Deferred" in `docs/TUTOR_AGENT.md`.

Check it came up configured:

```bash
curl -s localhost:8000/health     # {"status":"ok","tutor":"ready","missing_settings":[]}
```

### Frontend

```bash
cd frontend
bun install
cp .env.example .env.local        # already points at localhost:8000
bun dev
```

Then open `localhost:3000` → My courses → a course → New space → draw → tap a
tutor button.

### From a phone or tablet on the same network

The frontend targets whatever host served the page, so no frontend config is
needed. The backend must be told to accept that origin, and to listen beyond
loopback:

```bash
# backend, in place of the command above
CORS_ALLOW_ORIGINS=http://localhost:3000,http://YOUR-IP:3000 \
  .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# frontend
bun dev --hostname 0.0.0.0
```

`--host 0.0.0.0` exposes the API to your whole network, and on a machine with
a public address, to the internet. There is no authentication and every
request spends Gemini quota, so only do this on a trusted network and stop the
server afterwards.

## The tutor endpoint

`POST /api/tutor/analyze`, multipart form data:

```text
course_id          retrieval scope (carried; retrieval is deferred)
mode               mark | hint | explain | stuck
canvas_image       PNG, JPEG, or WebP; maximum 10 MB
prior_annotations  JSON array of normalized bounds; defaults to []
```

Full contract in `docs/TUTOR_AGENT.md`.

## Tests

```bash
cd backend  && .venv/bin/python -m pytest -q -m "not live"    # 101, no provider calls
cd frontend && bun run test                                    # 166
```

The opt-in live check spends one real Gemini request:

```bash
cd backend && RUN_LIVE_GEMINI=1 .venv/bin/python -m pytest -q -m live -s
```

Korey's credentialed RAG pipeline check needs the OpenAI and Pinecone keys:

```bash
cd backend && .venv/bin/python test_pipeline.py
```

## Team workstreams

- Jaden: whiteboard and frontend integration.
- Andre: AI/Vision and backend tutor APIs.
- Korey: course context ingestion and retrieval.
- Ren: question generation and learning engine (`ren/learning-engine`, not yet
  integrated — see "Deferred" in `docs/TUTOR_AGENT.md`).
