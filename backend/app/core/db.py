import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
if os.environ.get("VERCEL"):
    # Serverless: Neon's pooler (PgBouncer, transaction mode) does the pooling, and it cannot keep
    # server-side prepared statements, so psycopg must not create them.
    engine = create_engine(_settings.database_url, poolclass=NullPool, future=True,
                           connect_args={"prepare_threshold": None})
else:
    engine = create_engine(_settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
