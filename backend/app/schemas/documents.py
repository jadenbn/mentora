from enum import Enum
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentType(str, Enum):
    lecture = "lecture"
    assignment = "assignment"
    exam = "exam"
    practice_exam = "practice_exam"
    syllabus = "syllabus"
    formula_sheet = "formula_sheet"
    other = "other"


class ChunkMetadata(StrictModel):
    chunk_id: str
    course_id: str
    document_id: str
    chunk_index: int = Field(ge=0)
    filename: str
    page: int = Field(ge=1)
    document_type: DocumentType
    text: str = Field(min_length=1)


class RetrievedChunk(ChunkMetadata):
    """A chunk plus how well it matched. Text comes from SQLite, score from
    Pinecone; `app/services/retrieval.py` is what puts them together."""

    score: float


class CourseDocument(StrictModel):
    document_id: str
    course_id: str
    filename: str
    document_type: DocumentType
    total_chunks: int = Field(ge=1)
    total_pages: int = Field(ge=1)
    extracted_characters: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class IngestionResult(CourseDocument):
    # True when this ingest replaced an earlier copy of the same document.
    replaced_existing: bool = False
