"""One-shot: migrate old SQLite logs.db into the Postgres logs table.

Reports outcome by POSTing marker rows into the gateway itself so the
result is visible in the dashboard logs (sidecar stdout is not exposed
by Coolify).
"""
import os
import sqlite3
import sys
import traceback
import urllib.request

import psycopg2

SQLITE_PATH = os.environ.get("SQLITE_PATH", "/sqlite/logs.db")
PG_DSN = os.environ.get(
    "PG_DSN",
    "host=postgres port=5432 user=bifrost password=0690a8f3368cc0cd29060de48979f05d dbname=bifrost_logs",
)
VK = os.environ.get("VK", "")
GATEWAY = os.environ.get("GATEWAY", "http://bifrost:3000")


def report(status_code, detail=""):
    """Ping list_models N times so the dashboard shows marker rows."""
    if not VK:
        print("no VK for reporting", flush=True)
        return
    body = b"{}"
    for _ in range(status_code):
        try:
            req = urllib.request.Request(
                f"{GATEWAY}/v1/models",
                data=body,
                headers={"Authorization": f"Bearer {VK}"},
                method="GET",
            )
            urllib.request.urlopen(req, timeout=30)
        except Exception as e:
            print("report ping failed:", e, flush=True)
    print(f"reported status {status_code}: {detail}", flush=True)


def main():
    print("=== migrate start ===", flush=True)
    try:
        # locate sqlite file
        candidates = [SQLITE_PATH, "/sqlite/logs.db", "/sqlite/db/logs.db"]
        path = next((p for p in candidates if os.path.exists(p)), None)
        if not path:
            print("FATAL: sqlite db not found. /sqlite has:", os.listdir("/sqlite") if os.path.exists("/sqlite") else "(no mount)", flush=True)
            report(1, "sqlite not found")
            return 1
        print("using sqlite:", path, flush=True)

        lite = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        lite_count = lite.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        lite_cols = {r[1] for r in lite.execute("PRAGMA table_info(logs)")}
        print(f"sqlite: {lite_count} rows, {len(lite_cols)} cols", flush=True)

        pg = psycopg2.connect(PG_DSN)
        pgcur = pg.cursor()
        pgcur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='logs'")
        pg_cols = {r[0] for r in pgcur.fetchall()}
        common = [c for c in sorted(lite_cols & pg_cols) if c != "inc_number"]
        print(f"pg cols: {len(pg_cols)}, common: {len(common)}", flush=True)
        print("sqlite-only skipped:", sorted(lite_cols - pg_cols), flush=True)

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
        total = pgcur.fetchone()[0]
        print(f"DONE: inserted {inserted}, pg total {total}", flush=True)
        pg.close()
        report(2, f"migrated {inserted}, total {total}")
        return 0
    except Exception:
        traceback.print_exc()
        report(3, "exception")
        return 1


if __name__ == "__main__":
    sys.exit(main())
