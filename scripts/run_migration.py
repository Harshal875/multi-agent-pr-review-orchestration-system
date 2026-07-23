"""Apply a .sql migration to the Tiger Cloud database and verify the result.

Reads TIGER_DATABASE_URL from backend/.env, runs the given migration file,
then prints the extensions, tables, hypertables, and continuous aggregates so
Phase 13's Definition of Done can be checked at a glance.

Usage:
    python scripts/run_migration.py scripts/migrations/2026-06-tiger-init.sql
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / "backend" / ".env"


def load_db_url() -> str:
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line.startswith("TIGER_DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"TIGER_DATABASE_URL not found in {ENV_PATH}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/run_migration.py <path-to.sql>")

    sql_path = Path(sys.argv[1])
    if not sql_path.is_absolute():
        sql_path = ROOT / sql_path
    sql = sql_path.read_text()

    db_url = load_db_url()
    print(f"Connecting to Tiger Cloud ...")

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            print(f"Running migration: {sql_path.name}")
            cur.execute(sql)
            print("Migration applied.\n")

            print("== Extensions ==")
            cur.execute(
                "SELECT extname, extversion FROM pg_extension "
                "WHERE extname IN ('vector','vectorscale','timescaledb') "
                "ORDER BY extname;"
            )
            for name, ver in cur.fetchall():
                print(f"  {name:14} {ver}")

            print("\n== Tables ==")
            cur.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname='public' ORDER BY tablename;"
            )
            for (t,) in cur.fetchall():
                print(f"  {t}")

            print("\n== Hypertables ==")
            cur.execute(
                "SELECT hypertable_name FROM timescaledb_information.hypertables "
                "ORDER BY hypertable_name;"
            )
            rows = cur.fetchall()
            for (h,) in rows:
                print(f"  {h}")
            if not rows:
                print("  (none)")

            print("\n== Continuous aggregates ==")
            cur.execute(
                "SELECT view_name FROM timescaledb_information.continuous_aggregates "
                "ORDER BY view_name;"
            )
            rows = cur.fetchall()
            for (v,) in rows:
                print(f"  {v}")
            if not rows:
                print("  (none)")

            print("\n== Indexes on code_chunks ==")
            cur.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename='code_chunks' ORDER BY indexname;"
            )
            for (i,) in cur.fetchall():
                print(f"  {i}")

    print("\nDone.")


if __name__ == "__main__":
    main()
