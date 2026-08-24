"""Quick test of the RAG pipeline without needing the API server."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Check env vars are set
for key in ["OPENAI_API_KEY", "PINECONE_API_KEY", "PINECONE_INDEX_NAME"]:
    if not os.environ.get(key):
        print(f"❌ Missing {key} in .env")
        exit(1)

print("✓ Environment variables loaded")

# Test imports
from app.services.extraction import extract_document
from app.services.chunking import chunk_pages
from app.services.embeddings import embed_texts, upsert_chunks, query_similar
from app.schemas.documents import DocumentType

print("✓ All imports successful")

# Test with a real PDF from your room materials
test_pdf = Path("test_data/sample.pdf")
if not test_pdf.exists():
    print(f"\n⚠️  No test PDF found at {test_pdf}")
    print("   To test extraction & chunking, place a PDF at backend/test_data/sample.pdf")
    print("   For now, testing embeddings with mock data...\n")

    # Test embeddings with mock texts
    mock_texts = [
        "The derivative of sin(x) is cos(x).",
        "Integration by parts: ∫u dv = uv - ∫v du",
    ]
    print(f"Embedding {len(mock_texts)} mock texts...")
    embeddings = embed_texts(mock_texts)
    print(f"✓ Generated {len(embeddings)} embeddings of dimension {len(embeddings[0])}")
else:
    print(f"\nTesting full pipeline with {test_pdf.name}...\n")

    # 1. Extract
    print("1. Extracting text from PDF...")
    pages = extract_document(test_pdf)
    print(f"   ✓ Extracted {len(pages)} pages")
    if pages:
        print(f"   ✓ First page has {len(pages[0].text)} characters")

    # 2. Chunk
    print("\n2. Chunking with metadata...")
    chunks = chunk_pages(
        pages=pages,
        room_id="test_room_001",
        document_id="test_doc_001",
        filename=test_pdf.name,
        document_type=DocumentType.syllabus,
    )
    print(f"   ✓ Generated {len(chunks)} chunks")
    if chunks:
        print(f"   ✓ First chunk: {chunks[0].text[:100]}...")

    # 3. Embed & Upsert
    print("\n3. Embedding and upserting to Pinecone...")
    count = upsert_chunks(chunks)
    print(f"   ✓ Upserted {count} vectors to Pinecone")

    # 4. Retrieve
    print("\n4. Testing retrieval...")
    query = "What is the room about?"
    results = query_similar(query=query, room_id="test_room_001", top_k=3)
    print(f"   ✓ Found {len(results)} results for '{query}'")
    for i, result in enumerate(results, 1):
        print(f"      [{i}] {result['filename']} (page {result['page']}, score={result['score']:.3f})")
        print(f"          {result['text'][:80]}...\n")

print("\n✅ Pipeline test complete!")
