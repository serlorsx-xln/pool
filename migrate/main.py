"""One-shot: migrate old SQLite logs.db into the Postgres logs table."""
import os
import sqlite3
import sys
import traceback

import psycopg2

SQLITE_PATH = os.environ.get("SQLITE_PATH", "/sqlite/logs.db")
PG_DSN = os.environ.get(
    "PG_DSN",
    "host=postgres port=5432 user=bifrost password=0690a8f3368cc0cd29060de48979f05d dbname=bifrost_logs",
)

def main():
    print("=== migrate start ===", flush=True)
    print("sqlite path:", SQLITE_PATH, flush=True)
    print("exists:", os.path.exists(SQLITE_PATH), flush=True)
    if os.path.exists("/sqlite"):
        print("volume contents:", os.listdir("/sqlite"), flush=True)
        dbdir = "/sqlite/db" if os.path.isdir("/sqlite/db") else None
        if dbdir:
            print("db dir contents:", os.listdir(dbdir), flush=True)
            if not os.path.exists(SQLITE_PATH):
                SQLITE_PATH2 = os.path.join(dbdir, "logs.db")
                if os.path.exists(SQLITE_PATH2):
                    globals()["SQLITE_PATH"] = SQLITE_PATH2
    if not os.path.exists(SQLITE_PATH):
        print("FATAL: sqlite db not found", flush=True)
        return 1
    try:
        lite = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
        lite_count = lite.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        print(f"sqlite rows: {lite_count}", flush=True)
        lite_cols = {r[1] for r in lite.execute("PRAGMA table_info(logs)")}
        print(f"sqlite cols: {len(lite_cols)}", flush=True)

        pg = psycopg2.connect(PG_DSN)
        pgcur = pg.cursor()
        pgcur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='logs'")
        pg_cols = {r[0] for r in pgcur.fetchall()}
        print(f"pg cols: {len(pg_cols)}", flush=True)

        common = [c for c in sorted(lite_cols & pg_cols) if c != "inc_number"]
        print(f"common: {len(common)}", flush=True)
        print("skipped sqlite-only:", sorted(lite_cols - pg_cols)[:20], flush=True)

        col_list = ", ".join(f'"{c}"' for c in common)
        placeholders = ", ".join(["%s"] * len(common))
        sql = f'INSERT INTO logs ({col_list}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING'

        inserted = 0
        batch = []
        BATCH = 500
        for row in lite.execute(f"SELECT {col_list} FROM logs"):
            vals = [None if (isinstance(v, str) and v == "") else v for v in row]
            batch.append(tuple(vals))
            if len(batch) >= BATCH:
                pgcur.executemany(sql, batch)
                inserted += pgcur.rowcount
                pg.commit()
                batch = []
        if batch:
            pgcur.executemany(sql, batch)
            inserted += pgcur.rowcount
            pg.commit()
        pgcur.execute("SELECT COUNT(*) FROM logs")
        print(f"DONE: inserted {inserted}, pg total now {pgcur.fetchone()[0]}", flush=True)
        pg.close()
        return 0
    except Exception:
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
