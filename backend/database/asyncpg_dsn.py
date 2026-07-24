"""Shared DSN/SSL helper for raw asyncpg connections to Tiger Cloud. Used by any module
that needs a direct asyncpg pool rather than the SQLAlchemy engine in postgres.py -
memory/tiger_client.py's hot retrieval path and observability/events.py's event writes
both need this same shape. asyncpg doesn't understand the libpq sslmode query param, so
it's stripped here and SSL is passed as a connect kwarg instead."""

from __future__ import annotations

import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def dsn_and_ssl(url: str) -> tuple[str, ssl.SSLContext | None]:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    sslmode = query.pop("sslmode", None)
    dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    is_local = parts.hostname in ("localhost", "127.0.0.1")
    ctx = None if (is_local or sslmode in ("disable",)) else ssl.create_default_context()
    return dsn, ctx
