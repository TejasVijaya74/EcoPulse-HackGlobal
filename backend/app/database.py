from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL


def normalize_database_url(database_url: str) -> str:
    """Normalize Render and legacy PostgreSQL URLs to the installed psycopg 3 driver."""
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql", "postgresql+psycopg2"}:
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


DATABASE_URL = normalize_database_url(DATABASE_URL)
connect_args = {"check_same_thread": False} if make_url(DATABASE_URL).get_backend_name() == "sqlite" else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
