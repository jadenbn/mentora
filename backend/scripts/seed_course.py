"""Index the demo course's documents, then prove retrieval can find them.

    cd backend && PYTHONPATH=. .venv/bin/python scripts/seed_course.py [--reset]

Spends OpenAI embedding quota and writes to Pinecone. Safe to re-run: document
ids are content-addressed, so re-seeding replaces a document's chunks rather
than duplicating them.

`--reset` deletes everything already indexed for the course first, making the
index match `seed_data/` exactly. Earlier versions of the pipeline minted a
random document id per upload and used a different vector-id format, so their
chunks cannot be replaced by re-seeding and survive as duplicates that crowd
out real results. Deleting the course is the only way to clear them.

This script is the only record of how `course_demo` was indexed. The vectors
live in Pinecone, not in this repository, so a fresh clone, a teammate's own
Pinecone account, or a renamed index all leave retrieval finding nothing — and
an empty index is silent rather than an error, which is why seeding ends with a
query it must be able to answer.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.config import database_path  # noqa: E402
from app.database import CourseRepository  # noqa: E402
from app.schemas.documents import DocumentType  # noqa: E402
from app.services.embeddings import delete_course_vectors  # noqa: E402
from app.services.ingestion import ingest_document  # noqa: E402
from app.services.retrieval import search_course  # noqa: E402

#: Ingestion has its own credentials. The tutor's GEMINI_API_KEY is unrelated
#: and is not needed here.
REQUIRED_SETTINGS = ("OPENAI_API_KEY", "PINECONE_API_KEY", "PINECONE_INDEX_NAME")

#: The course the frontend already sends and the tutor already carries.
COURSE_ID = "course_demo"

SEED_DIR = Path(__file__).resolve().parent.parent / "seed_data"
DOCUMENTS: tuple[tuple[str, DocumentType], ...] = (
    ("Lecture12-ChainRule.pdf", DocumentType.lecture),
)

#: Something the seeded material must be able to answer.
PROBE_QUERY = "chain rule"


def main(reset: bool = False) -> None:
    missing = [name for name in REQUIRED_SETTINGS if not os.getenv(name)]
    if missing:
        # Names only, never values — same rule as /health.
        raise SystemExit(f"not configured; set {', '.join(missing)} in backend/.env")

    repository = CourseRepository(database_path())
    print(f"database {repository.path}")

    if reset:
        # Both stores, or the survivor becomes an orphan: rows nothing can
        # find, or vectors pointing at rows that are gone.
        removed_rows = repository.delete_course(COURSE_ID)
        removed_vectors = delete_course_vectors(COURSE_ID)
        print(
            f"reset {COURSE_ID}: removed {removed_rows} chunks "
            f"and {removed_vectors} vectors"
        )

    for filename, document_type in DOCUMENTS:
        path = SEED_DIR / filename
        if not path.exists():
            raise SystemExit(f"missing seed document: {path}")

        try:
            result = ingest_document(
                file_path=path,
                course_id=COURSE_ID,
                repository=repository,
                document_type=document_type,
                filename=filename,
            )
        except ValueError as exc:
            raise SystemExit(f"{filename}: {exc}") from exc

        verb = "replaced" if result.replaced_existing else "indexed"
        print(
            f"{verb} {result.filename}: "
            f"{result.total_chunks} chunks from {result.total_pages} pages"
        )

    matches = search_course(
        query=PROBE_QUERY, course_id=COURSE_ID, repository=repository, top_k=3
    )
    if not matches:
        raise SystemExit(
            f"indexed, but {COURSE_ID} returned no matches for {PROBE_QUERY!r}"
        )

    print(f"\nretrieval check — {PROBE_QUERY!r} in {COURSE_ID}:")
    for i, match in enumerate(matches, 1):
        print(f"  [{i}] {match.filename} p{match.page}  score {match.score:.3f}")
        print(f"      {match.text[:80].strip()}...")


if __name__ == "__main__":
    main(reset="--reset" in sys.argv[1:])
