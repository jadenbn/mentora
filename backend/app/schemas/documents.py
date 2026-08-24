from pydantic import BaseModel
from enum import Enum


class DocumentType(str, Enum):
    lecture = "lecture"
    assignment = "assignment"
    exam = "exam"
    practice_exam = "practice_exam"
    syllabus = "syllabus"
    formula_sheet = "formula_sheet"
    other = "other"


class ChunkMetadata(BaseModel):
    room_id: str
    document_id: str
    filename: str
    page: int
    document_type: DocumentType
    text: str


class IngestionResult(BaseModel):
    document_id: str
    filename: str
    total_chunks: int
    total_pages: int
    # True when this ingest replaced an earlier copy of the same document.
    replaced_existing: bool = False
