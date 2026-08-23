# Course-ingestion test suite

Deterministic coverage for the upload -> extract -> chunk -> embed -> index
pipeline and the two document routes.

## Running

```bash
cd backend
pip install -r requirements.txt
pytest                 # offline suite, no credentials needed
pytest -m live         # additionally hits real OpenAI + Pinecone
```

The offline suite replaces both providers with fakes
(`tests/ingestion_helpers.py`), so it needs no API keys and no network. PDFs in
these tests are real PDFs generated with PyMuPDF, so extraction runs through the
same code path production uses.

## Layout

| File | Covers |
| --- | --- |
| `test_extraction.py` | `services/extraction.py` — PDF/TXT/MD routing, page numbering, blank pages |
| `test_chunking.py` | `services/chunking.py` — split sizes, metadata propagation, page attribution |
| `test_embeddings.py` | `services/embeddings.py` — embedding calls, vector ids, batching, course-scoped query |
| `test_ingestion.py` | `services/ingestion.py` — orchestration and counts |
| `test_documents_api.py` | `api/documents.py` — status codes, validation, temp-file lifecycle |
| `test_documents_schemas.py` | `schemas/documents.py` — required fields and enum coercion |
| `test_live_ingestion.py` | real round trip, skipped without credentials |

`ingestion_helpers.py` is named to avoid colliding with the tutor suite's
`helpers.py` when both land on the same branch.

## Behaviour these tests pin down

Each of these currently passes — the tests record what the code does today so a
change to it is visible, rather than asserting the behaviour is correct.

- **Re-uploading a document duplicates every vector.** `document_id` is a fresh
  uuid per ingest, so ids never collide and Pinecone accumulates a second copy.
  There is no delete path.
- **An empty or text-free document reports success.** Zero pages and zero chunks
  return 200, so a scanned PDF with no text layer silently produces an unusable
  course.
- **`top_k` is unvalidated.** Zero and negative values reach Pinecone rather
  than returning 422.
- **Blank PDF pages are skipped but numbering is positional**, so a citation of
  "page 3" refers to the third physical page.
