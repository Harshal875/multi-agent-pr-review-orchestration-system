"""Formalizes the delivery_id (X-GitHub-Delivery) idempotency check from Phase 3
(database/repository.create_pending_review) into a reusable helper: any insert keyed by
a unique external ID gets the same idempotent-insert-or-fetch shape - ON CONFLICT DO
NOTHING ... RETURNING, then fall back to fetching the pre-existing row - without
hand-rolling that dance at every call site. database/repository.py uses this directly."""

from __future__ import annotations

from typing import Awaitable, Callable, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT")


async def idempotent_insert(
    session: AsyncSession,
    insert_stmt,
    fetch_existing: Callable[[], Awaitable[ModelT | None]],
) -> tuple[ModelT, bool]:
    """Execute an insert statement built with `.on_conflict_do_nothing(...).returning(...)`.
    If a row was inserted, returns (row, True). If the unique key already existed (no
    row returned), calls fetch_existing() and returns (existing_row, False) - a
    replayed delivery is a no-op, not an error."""
    result = await session.execute(insert_stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        await session.commit()
        return row, True

    existing = await fetch_existing()
    assert existing is not None  # UNIQUE conflict implies a row exists
    return existing, False
