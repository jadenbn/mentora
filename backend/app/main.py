from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

from app.api.documents import router as documents_router  # noqa: E402
from app.api.questions import router as questions_router  # noqa: E402
from app.api.tutor import router as tutor_router  # noqa: E402
from app.bootstrap import (  # noqa: E402
    learning_engine_lifespan,
    register_learning_engine,
)
from app.config import (  # noqa: E402
    api_key,
    cors_allow_origins,
    missing_indexing_settings,
    missing_settings,
)

app = FastAPI(title="Mentora API", lifespan=learning_engine_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    """Gate /api and /dev behind a shared key when one is configured.

    Off when MENTORA_API_KEY is unset, so local development is unchanged.
    /health stays open so a deployment can be probed without the key, and
    CORS preflight is exempt because a browser never attaches headers to it.
    """
    expected = api_key()
    path = request.url.path
    if (
        expected is not None
        and request.method != "OPTIONS"
        and (path.startswith("/api") or path.startswith("/dev"))
    ):
        if request.headers.get("x-api-key") != expected:
            return JSONResponse({"detail": "Not authorized"}, status_code=401)
    return await call_next(request)


app.include_router(documents_router)
app.include_router(questions_router)
app.include_router(tutor_router)
register_learning_engine(app)  # learning routes last


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
        "learning_engine": "ready",
    }
