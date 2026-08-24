"""SQLite repository for course documents and their chunk text.

Chunk text lives here; only its embedding lives in Pinecone. A vector search
returns chunk ids, which this module turns back into text — see
`app/services/retrieval.py`.

Taken from `andre/reformed`, narrowed to the document and chunk halves. The
`generated_problems` and `problem_grounding_chunks` tables on that branch stay
with question generation, which owns them. Keeping the shared parts identical
means adopting his branch later is an addition rather than a reconciliation.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.schemas.documents import ChunkMetadata, CourseDocument, DocumentType

#: SQLite caps a statement at 999 host parameters.
_QUERY_PARAM_LIMIT = 900

SCHEMA = """
CREATE TABLE IF NOT EXISTS course_documents (
    document_id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    document_type TEXT NOT NULL,
    total_pages INTEGER NOT NULL,
    total_chunks INTEGER NOT NULL,
    extracted_characters INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_course_documents_course_id
    ON course_documents(course_id);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES course_documents(document_id) ON DELETE CASCADE,
    course_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    page INTEGER NOT NULL,
    text TEXT NOT NULL,
    UNIQUE(document_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS ix_document_chunks_document_id
    ON document_chunks(document_id, chunk_index);
CREATE INDEX IF NOT EXISTS ix_document_chunks_course_id
    ON document_chunks(course_id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CourseRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def replace_document(
        self,
        *,
        document_id: str,
        course_id: str,
        filename: str,
        document_type: DocumentType,
        total_pages: int,
        chunks: list[ChunkMetadata],
    ) -> tuple[CourseDocument, bool]:
        now = _now()
        extracted_characters = sum(len(chunk.text) for chunk in chunks)
        with self.connect() as connection:
            previous = connection.execute(
                "SELECT created_at FROM course_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            created_at = previous["created_at"] if previous else now
            connection.execute(
                """
                INSERT INTO course_documents (
                    document_id, course_id, filename, document_type, total_pages,
                    total_chunks, extracted_characters, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    course_id=excluded.course_id,
                    filename=excluded.filename,
                    document_type=excluded.document_type,
                    total_pages=excluded.total_pages,
                    total_chunks=excluded.total_chunks,
                    extracted_characters=excluded.extracted_characters,
                    updated_at=excluded.updated_at
                """,
                (
                    document_id,
                    course_id,
                    filename,
                    document_type.value,
                    total_pages,
                    len(chunks),
                    extracted_characters,
                    created_at,
                    now,
                ),
            )
            for chunk in chunks:
                connection.execute(
                    """
                    INSERT INTO document_chunks (
                        chunk_id, document_id, course_id, chunk_index, page, text
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        course_id=excluded.course_id,
                        chunk_index=excluded.chunk_index,
                        page=excluded.page,
                        text=excluded.text
                    """,
                    (
                        chunk.chunk_id,
                        document_id,
                        course_id,
                        chunk.chunk_index,
                        chunk.page,
                        chunk.text,
                    ),
                )
            kept = [chunk.chunk_id for chunk in chunks]
            if kept:
                placeholders = ",".join("?" for _ in kept)
                connection.execute(
                    f"DELETE FROM document_chunks WHERE document_id = ? AND chunk_id NOT IN ({placeholders})",
                    (document_id, *kept),
                )
        document = self.get_document(course_id=course_id, document_id=document_id)
        assert document is not None
        return document, previous is not None

    def list_documents(self, course_id: str) -> list[CourseDocument]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM course_documents WHERE course_id = ? ORDER BY updated_at DESC",
                (course_id,),
            ).fetchall()
        return [self._document(row) for row in rows]

    def get_document(self, *, course_id: str, document_id: str) -> CourseDocument | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM course_documents WHERE course_id = ? AND document_id = ?",
                (course_id, document_id),
            ).fetchone()
        return self._document(row) if row else None

    def get_chunks_by_ids(self, chunk_ids: list[str]) -> dict[str, ChunkMetadata]:
        """Hydrate chunks by id, keyed by id.

        Returns a mapping rather than a list because the caller holds the
        ranking: a vector search decides the order, and this only supplies the
        text. Ids that no longer exist are simply absent, which is how a stale
        vector surfaces as a missing chunk instead of a crash.

        `filename` and `document_type` live on the document, so this joins
        rather than duplicating them onto every chunk row.
        """
        if not chunk_ids:
            return {}

        found: dict[str, ChunkMetadata] = {}
        with self.connect() as connection:
            for i in range(0, len(chunk_ids), _QUERY_PARAM_LIMIT):
                batch = chunk_ids[i : i + _QUERY_PARAM_LIMIT]
                placeholders = ",".join("?" for _ in batch)
                rows = connection.execute(
                    f"""
                    SELECT c.chunk_id, c.course_id, c.document_id, c.chunk_index,
                           c.page, c.text, d.filename, d.document_type
                    FROM document_chunks c
                    JOIN course_documents d ON d.document_id = c.document_id
                    WHERE c.chunk_id IN ({placeholders})
                    """,
                    batch,
                ).fetchall()
                for row in rows:
                    found[row["chunk_id"]] = ChunkMetadata(
                        chunk_id=row["chunk_id"],
                        course_id=row["course_id"],
                        document_id=row["document_id"],
                        chunk_index=row["chunk_index"],
                        filename=row["filename"],
                        page=row["page"],
                        document_type=DocumentType(row["document_type"]),
                        text=row["text"],
                    )
        return found

    def delete_document(self, *, course_id: str, document_id: str) -> int:
        """Remove a document and its chunks. Returns chunks deleted."""
        with self.connect() as connection:
            deleted = connection.execute(
                "DELETE FROM document_chunks WHERE course_id = ? AND document_id = ?",
                (course_id, document_id),
            ).rowcount
            connection.execute(
                "DELETE FROM course_documents WHERE course_id = ? AND document_id = ?",
                (course_id, document_id),
            )
        return deleted

    def delete_course(self, course_id: str) -> int:
        """Remove every document and chunk for a course. Returns chunks deleted."""
        with self.connect() as connection:
            deleted = connection.execute(
                "DELETE FROM document_chunks WHERE course_id = ?", (course_id,)
            ).rowcount
            connection.execute(
                "DELETE FROM course_documents WHERE course_id = ?", (course_id,)
            )
        return deleted

    @staticmethod
    def _document(row: sqlite3.Row) -> CourseDocument:
        return CourseDocument(
            document_id=row["document_id"],
            course_id=row["course_id"],
            filename=row["filename"],
            document_type=DocumentType(row["document_type"]),
            total_pages=row["total_pages"],
            total_chunks=row["total_chunks"],
            extracted_characters=row["extracted_characters"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
