"""Small additive SQLite repository for course documents and generated problems."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from app.schemas.documents import ChunkMetadata, CourseDocument, DocumentType
from app.schemas.problems import GeneratedProblem, GroundedProblem, GroundingChunk, ProblemContext


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

CREATE TABLE IF NOT EXISTS generated_problems (
    problem_id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL,
    document_id TEXT NOT NULL REFERENCES course_documents(document_id),
    prompt TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_generated_problems_course_id
    ON generated_problems(course_id);

CREATE TABLE IF NOT EXISTS problem_grounding_chunks (
    problem_id TEXT NOT NULL REFERENCES generated_problems(problem_id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL REFERENCES document_chunks(chunk_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    PRIMARY KEY(problem_id, chunk_id),
    UNIQUE(problem_id, ordinal)
);
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

    def get_chunks(self, *, course_id: str, document_id: str) -> list[GroundingChunk]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT chunk_id, page, text FROM document_chunks
                WHERE course_id = ? AND document_id = ? ORDER BY chunk_index
                """,
                (course_id, document_id),
            ).fetchall()
        return [GroundingChunk.model_validate(dict(row)) for row in rows]

    def create_problem(
        self,
        *,
        problem: ProblemContext,
        grounding_chunk_ids: Iterable[str],
    ) -> GeneratedProblem:
        created_at = _now()
        ids = list(dict.fromkeys(grounding_chunk_ids))
        with self.connect() as connection:
            valid_rows = connection.execute(
                """
                SELECT chunk_id FROM document_chunks
                WHERE course_id = ? AND document_id = ?
                """,
                (problem.course_id, problem.document_id),
            ).fetchall()
            valid = {row["chunk_id"] for row in valid_rows}
            if not ids or any(chunk_id not in valid for chunk_id in ids):
                raise ValueError("grounding chunks must belong to the problem document")
            connection.execute(
                """
                INSERT INTO generated_problems (
                    problem_id, course_id, document_id, prompt, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (problem.id, problem.course_id, problem.document_id, problem.prompt, created_at),
            )
            connection.executemany(
                """
                INSERT INTO problem_grounding_chunks (problem_id, chunk_id, ordinal)
                VALUES (?, ?, ?)
                """,
                [(problem.id, chunk_id, ordinal) for ordinal, chunk_id in enumerate(ids)],
            )
        return GeneratedProblem(**problem.model_dump(), created_at=created_at)

    def get_grounded_problem(self, *, course_id: str, problem_id: str) -> GroundedProblem | None:
        with self.connect() as connection:
            problem_row = connection.execute(
                """
                SELECT problem_id, course_id, document_id, prompt
                FROM generated_problems WHERE course_id = ? AND problem_id = ?
                """,
                (course_id, problem_id),
            ).fetchone()
            if problem_row is None:
                return None
            chunk_rows = connection.execute(
                """
                SELECT c.chunk_id, c.page, c.text
                FROM problem_grounding_chunks AS g
                JOIN document_chunks AS c ON c.chunk_id = g.chunk_id
                WHERE g.problem_id = ? ORDER BY g.ordinal
                """,
                (problem_id,),
            ).fetchall()
        problem = ProblemContext(
            id=problem_row["problem_id"],
            course_id=problem_row["course_id"],
            document_id=problem_row["document_id"],
            source="generated",
            prompt=problem_row["prompt"],
        )
        return GroundedProblem(
            problem=problem,
            chunks=[GroundingChunk.model_validate(dict(row)) for row in chunk_rows],
        )

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
