"""Async SQLAlchemy engine + session factory over the Tiger Cloud database.

The Tiger connection string is a libpq-style URL (postgres://...?sslmode=require).
asyncpg does not understand the sslmode query parameter, so we rewrite the scheme to
postgresql+asyncpg and translate SSL into connect_args. SQLAlchemy is the "normal
relational work" access style (ARCHITECTURE §2.4); asyncpg-direct is reserved for hot
paths in later phases."""

from __future__ import annotations

import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import settings


def _to_async_url(url: str) -> tuple[str, dict]:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    sslmode = query.pop("sslmode", None)
    async_url = urlunsplit(
        ("postgresql+asyncpg", parts.netloc, parts.path, urlencode(query), parts.fragment)
    )
    connect_args: dict = {}
    is_local = parts.hostname in ("localhost", "127.0.0.1")
    if sslmode not in (None, "disable", "allow", "prefer") and not is_local:
        connect_args["ssl"] = ssl.create_default_context()
    elif not is_local and sslmode is None:
        # Tiger requires SSL even when the param was stripped upstream.
        connect_args["ssl"] = ssl.create_default_context()
    return async_url, connect_args


_async_url, _connect_args = _to_async_url(settings.tiger_database_url)

engine = create_async_engine(
    _async_url,
    connect_args=_connect_args,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncSession:
    """FastAPI dependency: yields a session and always closes it."""
    async with SessionLocal() as session:
        yield session
