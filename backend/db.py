import os
from collections.abc import Iterator

from dotenv import load_dotenv
from sqlalchemy import inspect, text
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine

load_dotenv()

# Supabase: use the Session pooler URI (IPv4) from Project Settings → Database → Connect.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./aqylroute.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
elif os.getenv("VERCEL"):
    # Serverless: no pool per short-lived instance; Supabase's transaction pooler (port 6543) does the pooling.
    engine = create_engine(DATABASE_URL, connect_args={"prepare_threshold": None}, poolclass=NullPool)
else:
    engine = create_engine(
        DATABASE_URL,
        # prepare_threshold=None: Supabase's transaction pooler (port 6543) rejects prepared statements.
        connect_args={"prepare_threshold": None},
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


def create_db_and_tables() -> None:
    import models  # noqa: F401  register tables

    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        # create_all doesn't add columns to existing tables: users predates roles.
        if "role" not in {c["name"] for c in inspect(conn).get_columns("users")}:
            conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'parent'"))
    if not IS_SQLITE:
        # Block Supabase's public REST API (anon/authenticated roles) from reading our tables.
        # The backend connects as the postgres role, which bypasses RLS.
        with engine.begin() as conn:
            for table in SQLModel.metadata.tables:
                conn.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
