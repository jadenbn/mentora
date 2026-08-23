# Mentora

Mentora is a persistent, course-aware AI whiteboard tutor. A student works by
hand on a tldraw canvas, then asks for Mark, Hint, Explain, or I'm Stuck. The
backend retrieves relevant course material, uses a multimodal Gemini agent
workflow to interpret the work, and returns validated spatial actions for the
whiteboard renderer.

The tutor also emits evidence-based learning events and reads Ren's durable
student model so future feedback can adapt to what the student does well and
where they struggle.

## Repository

- `frontend/`: Next.js, React, and tldraw whiteboard UI.
- `backend/`: FastAPI course ingestion/retrieval and Gemini tutor services.
- `docs/PRODUCT.md`: authoritative product behavior.
- `docs/ARCHITECTURE.md`: system boundaries and shared contracts.
- `docs/TUTOR_AGENT.md`: tutor API, ADK workflow, and integration guide.

## Backend quick start

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Configure all four required integrations in `backend/.env`:

```text
GEMINI_API_KEY
OPENAI_API_KEY
PINECONE_API_KEY
PINECONE_INDEX_NAME
```

The tutor endpoint is `POST /api/tutor/analyze`. It accepts multipart form data
with a JSON `payload`, a required `canvas_image`, and an optional
`selection_image`. See `docs/TUTOR_AGENT.md` for complete examples.

The learning engine exposes explicit attempt ingestion, student-model reads,
and adaptive next-problem specifications under `/api/courses/{course_id}`.
Tutor actions do not silently create completed attempts.

## Tests

```bash
cd backend
.venv/bin/python -m pytest -q
```

The normal suite is deterministic and does not call providers. To run the
opt-in Gemini check after configuring a key:

```bash
RUN_LIVE_GEMINI_TEST=1 .venv/bin/python -m pytest -q -m live
```

Korey's credentialed RAG pipeline check remains available separately:

```bash
cd backend
.venv/bin/python test_pipeline.py
```

## Team workstreams

- Jaden: whiteboard and frontend integration.
- Andre: AI/Vision and backend tutor APIs.
- Korey: course context ingestion and retrieval.
- Ren: question generation and learning engine.
