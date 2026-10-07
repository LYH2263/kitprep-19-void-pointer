from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# 对已存在的旧库做幂等补列（create_all 不会给既有表加列）。
# 新增列必须有默认值，使历史备料单默认 active、历史库存预占为 0。
_PATCH_COLUMNS = {
    "ingredients": [("reserved_qty", "FLOAT NOT NULL DEFAULT 0.0")],
    "prep_runs": [("status", "VARCHAR(16) NOT NULL DEFAULT 'active'")],
}


def ensure_schema() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _PATCH_COLUMNS.items():
            if table not in existing_tables:
                continue  # 新库由 create_all 建出带新列的表
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
