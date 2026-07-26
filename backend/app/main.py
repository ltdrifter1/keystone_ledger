from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.engines.working_papers import ensure_working_paper_foundation
from app.services.seed import seed_if_empty

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seeded = seed_if_empty(db)
        if seeded:
            print("Seeded demo data (CA/US entities, chart, sample transactions)")
        foundation = ensure_working_paper_foundation(db)
        if foundation.get("accounts_created") or foundation.get("layouts_created"):
            print(
                "Working paper foundation ready "
                f"(+{foundation['accounts_created']} accounts, "
                f"+{foundation['layouts_created']} BS lines)"
            )
    finally:
        db.close()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Controller/CFO reporting tool — bank reconciliations, transaction management, and financial reporting.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}
