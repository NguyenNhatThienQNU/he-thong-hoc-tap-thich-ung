"""Kết nối cơ sở dữ liệu (SQLAlchemy 2)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from .config import ON_VERCEL


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)
_engine: Engine | None = None


def make_engine(url: str) -> Engine:
    is_sqlite = url.startswith("sqlite")
    connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
    if not is_sqlite and ON_VERCEL:
        # Hàm serverless: không giữ kết nối giữa các lần gọi
        engine = create_engine(url, poolclass=NullPool)
    else:
        engine = create_engine(url, connect_args=connect_args, pool_pre_ping=not is_sqlite)
    if is_sqlite:
        in_memory = ":memory:" in url or url.rstrip("/").endswith("sqlite:")

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - chỉ cấu hình
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            if not in_memory:
                cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def init_engine(url: str) -> Engine:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(url)
    SessionLocal.configure(bind=_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Chưa khởi tạo kết nối CSDL (init_engine).")
    return _engine


def create_tables() -> None:
    from . import models  # noqa: F401  (đăng ký các bảng)

    Base.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """Phiên làm việc tự commit khi thành công, rollback khi lỗi."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
