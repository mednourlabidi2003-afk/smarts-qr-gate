from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


class Base(DeclarativeBase):
    """Shared declarative base for the virtual gate models."""


def get_database_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://smarts:smarts@localhost:5432/qr_gate",
    )


def create_db_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_database_url()
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    elif url.startswith("postgresql") and "sslmode=" not in url:
        connect_args["sslmode"] = os.getenv("DATABASE_SSLMODE", "require")

    return create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    from .models import AccessLog, ReservationRecord  # noqa: F401

    Base.metadata.create_all(engine)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
