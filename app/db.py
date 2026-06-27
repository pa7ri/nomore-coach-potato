"""Database layer.

A single asyncpg pool, created at startup via :func:`init_pool` and torn down
via :func:`close_pool`. Every helper accepts the pool explicitly so handlers
can be tested with a fake.

All timestamps in the DB are TIMESTAMPTZ stored as UTC. Conversion to the
display TZ happens in the handlers.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import asyncpg

log = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"


# ---------- dataclasses ----------------------------------------------------

@dataclass(slots=True)
class Plan:
    id: int
    title: str
    description: Optional[str]
    starts_at: dt.datetime  # tz-aware UTC
    duration_min: Optional[int]
    price_cents: Optional[int]
    currency: Optional[str]
    location: Optional[str]
    link: Optional[str]
    created_by: int
    created_at: dt.datetime


@dataclass(slots=True)
class Movie:
    id: int
    title: str
    note: Optional[str]
    link: Optional[str]
    watched_at: Optional[dt.datetime]
    added_by: int
    added_at: dt.datetime


def _row_to_plan(r: asyncpg.Record) -> Plan:
    return Plan(
        id=r["id"],
        title=r["title"],
        description=r["description"],
        starts_at=r["starts_at"],
        duration_min=r["duration_min"],
        price_cents=r["price_cents"],
        currency=r["currency"],
        location=r["location"],
        link=r["link"],
        created_by=r["created_by"],
        created_at=r["created_at"],
    )


def _row_to_movie(r: asyncpg.Record) -> Movie:
    return Movie(
        id=r["id"],
        title=r["title"],
        note=r["note"],
        link=r["link"],
        watched_at=r["watched_at"],
        added_by=r["added_by"],
        added_at=r["added_at"],
    )


# ---------- lifecycle ------------------------------------------------------

async def init_pool() -> asyncpg.Pool:
    """Open the pool and run the schema. Supabase's pooled URL uses pgbouncer
    in transaction mode, which doesn't support prepared statements — we
    disable them by setting statement_cache_size=0."""
    dsn = os.environ["DATABASE_URL"]
    pool = await asyncpg.create_pool(
        dsn,
        min_size=1,
        max_size=5,
        statement_cache_size=0,
    )
    schema_sql = _SCHEMA_PATH.read_text()
    async with pool.acquire() as conn:
        await conn.execute(schema_sql)
    log.info("db pool ready, schema applied")
    return pool


async def close_pool(pool: asyncpg.Pool) -> None:
    await pool.close()


# ---------- plans ----------------------------------------------------------

async def insert_plan(
    pool: asyncpg.Pool,
    *,
    title: str,
    starts_at: dt.datetime,
    created_by: int,
    description: Optional[str] = None,
    duration_min: Optional[int] = None,
    price_cents: Optional[int] = None,
    currency: Optional[str] = "EUR",
    location: Optional[str] = None,
    link: Optional[str] = None,
) -> Plan:
    row = await pool.fetchrow(
        """
        INSERT INTO plans (title, description, starts_at, duration_min,
                           price_cents, currency, location, link, created_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING *
        """,
        title, description, starts_at, duration_min,
        price_cents, currency, location, link, created_by,
    )
    return _row_to_plan(row)


async def list_plans_between(
    pool: asyncpg.Pool, start: dt.datetime, end: dt.datetime
) -> list[Plan]:
    rows = await pool.fetch(
        "SELECT * FROM plans WHERE starts_at >= $1 AND starts_at < $2 ORDER BY starts_at",
        start, end,
    )
    return [_row_to_plan(r) for r in rows]


async def random_upcoming_plan(pool: asyncpg.Pool, now: dt.datetime) -> Optional[Plan]:
    row = await pool.fetchrow(
        "SELECT * FROM plans WHERE starts_at >= $1 ORDER BY random() LIMIT 1",
        now,
    )
    return _row_to_plan(row) if row else None


async def list_plans_page(
    pool: asyncpg.Pool, *, offset: int, limit: int
) -> tuple[list[Plan], int]:
    """Return one page of plans (newest-first by starts_at desc) plus total count."""
    rows = await pool.fetch(
        "SELECT * FROM plans ORDER BY starts_at DESC OFFSET $1 LIMIT $2",
        offset, limit,
    )
    total = await pool.fetchval("SELECT count(*) FROM plans")
    return [_row_to_plan(r) for r in rows], int(total or 0)


async def delete_plan(pool: asyncpg.Pool, plan_id: int) -> bool:
    result = await pool.execute("DELETE FROM plans WHERE id = $1", plan_id)
    # asyncpg returns "DELETE <n>"
    return result.endswith(" 1")


# ---------- movies ---------------------------------------------------------

async def insert_movie(
    pool: asyncpg.Pool,
    *,
    title: str,
    added_by: int,
    note: Optional[str] = None,
    link: Optional[str] = None,
) -> Movie:
    row = await pool.fetchrow(
        """
        INSERT INTO movies (title, note, link, added_by)
        VALUES ($1, $2, $3, $4)
        RETURNING *
        """,
        title, note, link, added_by,
    )
    return _row_to_movie(row)


async def list_unwatched_page(
    pool: asyncpg.Pool, *, offset: int, limit: int
) -> tuple[list[Movie], int]:
    rows = await pool.fetch(
        "SELECT * FROM movies WHERE watched_at IS NULL ORDER BY added_at DESC OFFSET $1 LIMIT $2",
        offset, limit,
    )
    total = await pool.fetchval(
        "SELECT count(*) FROM movies WHERE watched_at IS NULL"
    )
    return [_row_to_movie(r) for r in rows], int(total or 0)


async def random_unwatched_movie(pool: asyncpg.Pool) -> Optional[Movie]:
    row = await pool.fetchrow(
        "SELECT * FROM movies WHERE watched_at IS NULL ORDER BY random() LIMIT 1"
    )
    return _row_to_movie(row) if row else None


async def mark_watched(pool: asyncpg.Pool, movie_id: int) -> bool:
    result = await pool.execute(
        "UPDATE movies SET watched_at = now() WHERE id = $1 AND watched_at IS NULL",
        movie_id,
    )
    return result.endswith(" 1")


async def delete_movie(pool: asyncpg.Pool, movie_id: int) -> bool:
    result = await pool.execute("DELETE FROM movies WHERE id = $1", movie_id)
    return result.endswith(" 1")
