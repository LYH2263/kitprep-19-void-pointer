from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api.router import api_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.services.seed import seed_if_empty


def _ensure_columns() -> None:
    """轻量幂等迁移：给已存在的表补作废/占用新列（create_all 不改既有表）。"""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if "prep_runs" in tables:
        cols = {c["name"] for c in inspector.get_columns("prep_runs")}
        with engine.begin() as conn:
            if "status" not in cols:
                conn.execute(text("ALTER TABLE prep_runs ADD COLUMN status VARCHAR(16) DEFAULT 'active'"))
                conn.execute(text("UPDATE prep_runs SET status = 'active' WHERE status IS NULL"))
            if "voided_at" not in cols:
                conn.execute(text("ALTER TABLE prep_runs ADD COLUMN voided_at TIMESTAMP"))
    if "ingredients" in tables:
        cols = {c["name"] for c in inspector.get_columns("ingredients")}
        with engine.begin() as conn:
            if "reserved_qty" not in cols:
                conn.execute(text("ALTER TABLE ingredients ADD COLUMN reserved_qty FLOAT DEFAULT 0.0"))
                conn.execute(text("UPDATE ingredients SET reserved_qty = 0.0 WHERE reserved_qty IS NULL"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    if settings.seed_on_empty:
        db = SessionLocal()
        try:
            seed_if_empty(db)
        finally:
            db.close()
    yield


app = FastAPI(title="KitPrep", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")
