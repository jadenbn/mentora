from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.api.courses import router as courses_router  # noqa: E402
from app.api.documents import router as documents_router  # noqa: E402
from app.api.questions import router as questions_router  # noqa: E402
from app.api.spaces import router as spaces_router  # noqa: E402
from app.api.spaces import space_lookup_router  # noqa: E402
from app.api.tutor import router as tutor_router  # noqa: E402
from app.api.voice import router as voice_router  # noqa: E402
from app.config import (  # noqa: E402
    cors_allow_origins,
    missing_indexing_settings,
    missing_settings,
)

app = FastAPI(title="Mentora API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(courses_router)
app.include_router(documents_router)
app.include_router(questions_router)
app.include_router(spaces_router)
app.include_router(space_lookup_router)
app.include_router(tutor_router)
app.include_router(voice_router)


@app.get("/health")
async def health():
    """Always available. Reports missing variable names, never their values."""
    missing = missing_settings()
    missing_indexing = missing_indexing_settings()
    return {
        "status": "ok",
        "tutor": "ready" if not missing else "not_ready",
        "missing_settings": missing,
        "course_indexing": "ready" if not missing_indexing else "not_ready",
        "missing_indexing_settings": missing_indexing,
    }
