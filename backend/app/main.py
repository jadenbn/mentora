import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.documents import router as documents_router
from app.bootstrap import learning_engine_lifespan, register_learning_engine

load_dotenv()


def _cors_allow_origins() -> list[str]:
    # Stand-in for app.config.cors_allow_origins(), which doesn't exist on
    # this branch yet. Same env var, same default, so merging just swaps
    # this for the shared import.
    raw = os.getenv("CORS_ALLOW_ORIGINS") or "http://localhost:3000"
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = FastAPI(title="Mentora API", lifespan=learning_engine_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
register_learning_engine(app)


@app.get("/health")
async def health():
    return {"status": "ok"}
