"""Index the checked-in demo lecture and prove SQLite/Pinecone retrieval.

    cd backend && PYTHONPATH=. .venv/bin/python scripts/seed_course.py [--reset]
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.config import database_path, missing_indexing_settings  # noqa: E402
from app.database import CourseRepository  # noqa: E402
from app.schemas.documents import DocumentType  # noqa: E402
from app.services.embeddings import delete_course_vectors  # noqa: E402
from app.services.ingestion import ingest_document  # noqa: E402
from app.services.retrieval import search_document  # noqa: E402

COURSE_ID = "course_demo"
SEED_DOCUMENT = Path(__file__).resolve().parents[2] / "Lecture12-ChainRule.pdf"
PROBE_QUERY = "a conceptual chain-rule question"


def main(*, reset: bool = False) -> None:
    missing = missing_indexing_settings()
    if missing:
        raise SystemExit(f"not configured; set {', '.join(missing)} in backend/.env")
    if not SEED_DOCUMENT.exists():
        raise SystemExit(f"missing seed document: {SEED_DOCUMENT}")

    repository = CourseRepository(database_path())
    if reset:
        repository.delete_course(COURSE_ID)
        delete_course_vectors(COURSE_ID)

    result = ingest_document(
        file_path=SEED_DOCUMENT,
        course_id=COURSE_ID,
        repository=repository,
        document_type=DocumentType.lecture,
        filename=SEED_DOCUMENT.name,
    )
    matches = search_document(
        query=PROBE_QUERY,
        course_id=COURSE_ID,
        document_id=result.document_id,
        repository=repository,
        top_k=3,
    )
    if not matches:
        raise SystemExit("indexing completed, but the retrieval probe returned no chunks")
    print(
        f"indexed {result.total_chunks} chunks; "
        f"probe found {len(matches)} SQLite-backed matches"
    )
    for match in matches:
        print(f"  {match.chunk_id} page {match.page}: {match.text[:80].strip()}...")


if __name__ == "__main__":
    main(reset="--reset" in sys.argv[1:])
