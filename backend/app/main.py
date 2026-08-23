from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from sqlmodel import Session

from app.api.documents import router as documents_router
from app.api.learning import router as learning_router
from app.db import engine, init_db
from app.services.taxonomy import seed_all_courses

load_dotenv()

app = FastAPI(title="Mentora API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
app.include_router(learning_router)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    with Session(engine) as session:
        seed_all_courses(session)


@app.get("/health")
async def health():
    return {"status": "ok"}
