"""Chunk extracted pages and attach metadata."""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.schemas.documents import ChunkMetadata, DocumentType
from app.services.extraction import ExtractedPage

# Fixed-size chunks with ~12% overlap — good enough for hackathon RAG
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100

splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    length_function=len,
    separators=["\n\n", "\n", ". ", " ", ""],
)


def chunk_pages(
    pages: list[ExtractedPage],
    course_id: str,
    document_id: str,
    filename: str,
    document_type: DocumentType,
) -> list[ChunkMetadata]:
    """Split pages into chunks and attach metadata to each one."""
    chunks: list[ChunkMetadata] = []

    chunk_index = 0
    for page in pages:
        splits = splitter.split_text(page.text)
        for split in splits:
            chunks.append(
                ChunkMetadata(
                    chunk_id=f"chunk_{document_id}_{chunk_index:05d}",
                    course_id=course_id,
                    document_id=document_id,
                    chunk_index=chunk_index,
                    filename=filename,
                    page=page.page_number,
                    document_type=document_type,
                    text=split,
                )
            )
            chunk_index += 1

    return chunks
