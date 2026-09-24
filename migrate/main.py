"""One-shot: migrate old SQLite logs.db into the Postgres logs table.

Reads /sqlite/logs.db (old volume) and inserts every row into Postgres,
taking the intersection of columns (only columns that exist in BOTH the
SQLite table and the Postgres table are copied — schema drift is skipped,
not fatal). Uses INSERT ... ON CONFLICT (id) DO NOTHING so re-runs are
safe and rows already in Postgres (written live since the switch) are
never duplicated.
"""
import json
import os
import sqlite3
import sys

import psycopg2
import psycopg2.extras

SQLITE_PATH = os.environ.get("SQLITE_PATH", "/sqlite/logs.db")
PG_DSN = os.environ.get(
    "PG_DSN",
    "host=postgres port=5432 user=bifrost password=0690a8f3368cc0cd29060de48979f05d dbname=bifrost_logs",
)

SKIP_COLUMNS = {"inc_number"}  # sequence-managed in Postgres; let Postgres assign


def main():
    lite = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
    lite.row_factory = sqlite3.Row

    pg = psycopg2.connect(PG_DSN)
    pg.autocommit = False
    pgcur = pg.cursor()

    # 1) what does SQLite have?
    lite_cols = {r[1] for r in lite.execute("PRAGMA table_info(logs)")}
    if not lite_cols:
        print("no logs table in sqlite — nothing to migrate")
        return
    lite_count = lite.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
    print(f"sqlite: {lite_count} rows, {len(lite_cols)} columns")

    # 2) what does Postgres accept?
    pgcur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'logs'"
    )
    pg_cols = {r[0] for r in pgcur.fetchall()}
    print(f"postgres: {len(pg_cols)} columns")

    common = [c for c in sorted(lite_cols & pg_cols) if c not in SKIP_COLUMNS]
    print(f"common columns to copy: {len(common)}")
    skipped = sorted(lite_cols - pg_cols)
    if skipped:
        print(f"sqlite-only columns skipped: {skipped}")

    col_list = ", ".join(f'"{c}"' for c in common)
    placeholders = ", ".join(["%s"] * len(common))
    sql = f'INSERT INTO logs ({col_list}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING'

    inserted = 0
    conflicts = 0
    BATCH = 500
    rows = lite.execute(f"SELECT {col_list} FROM logs")
    batch = []
    for row in rows:
        vals = []
        for v in row:
            if isinstance(v, str) and v == "":
                v = None  # sqlite empty string -> pg nullable
            vals.append(v)
        batch.append(tuple(vals))
        if len(batch) >= BATCH:
            pgcur.executemany(sql, batch)
            inserted += pgcur.rowcount
            batch = []
            pg.commit()
    if batch:
        pgcur.executemany(sql, batch)
        inserted += pgcur.rowcount
        pg.commit()

    total = lite.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
    pgcur.execute("SELECT COUNT(*) FROM logs")
    pg_total = pgcur.fetchone()[0]
    print(f"done: sqlite had {total} rows, inserted (new) {inserted}, postgres now has {pg_total} rows")
    pg.close()
    lite.close()


if __name__ == "__main__":
    sys.exit(main())
