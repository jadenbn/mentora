from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.api.documents import router as documents_router  # noqa: E402
from app.api.tutor import router as tutor_router  # noqa: E402
from app.config import missing_settings  # noqa: E402

app = FastAPI(title="Mentora API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
app.include_router(tutor_router)


@app.get("/health")
async def health():
    """Always available. Reports missing variable names, never their values."""
    missing = missing_settings()
    return {
        "status": "ok",
        "tutor": "ready" if not missing else "not_ready",
        "missing_settings": missing,
    }
