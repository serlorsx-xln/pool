"""One-shot SQLite->Postgres log migration with progress markers via list_models."""
import os
import sqlite3
import sys
import time
import traceback
import urllib.request

import psycopg2

PG_DSN = "host=postgres port=5432 user=bifrost password=0690a8f3368cc0cd29060de48979f05d dbname=bifrost_logs"
VK = os.environ.get("VK", "")
GATEWAY = "http://bifrost:3000"


def ping():
    if not VK:
        print("no VK", flush=True)
        return
    try:
        req = urllib.request.Request(f"{GATEWAY}/v1/models", headers={"Authorization": f"Bearer {VK}"})
        urllib.request.urlopen(req, timeout=30)
        print("ping ok", flush=True)
    except Exception as e:
        print("ping FAILED:", e, flush=True)


def phase(n):
    """n pings = phase n reached."""
    for _ in range(n):
        ping()
        time.sleep(1)


def main():
    phase(1)  # container alive, script started
    try:
        cands = ["/sqlite/logs.db", "/sqlite/db/logs.db"]
        path = next((p for p in cands if os.path.exists(p)), None)
        if not path:
            print("FATAL no sqlite:", os.listdir("/sqlite") if os.path.exists("/sqlite") else "no mount", flush=True)
            phase(4)
            return 1
        print("sqlite:", path, flush=True)

        lite = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        n = lite.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        print("sqlite rows:", n, flush=True)
        lite_cols = {r[1] for r in lite.execute("PRAGMA table_info(logs)")}

        phase(2)  # sqlite read ok

        pg = psycopg2.connect(PG_DSN)
        cur = pg.cursor()
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='logs'")
        pg_cols = {r[0] for r in cur.fetchall()}
        common = [c for c in sorted(lite_cols & pg_cols) if c != "inc_number"]
        print("common cols:", len(common), flush=True)

        col_list = ", ".join(f'"{c}"' for c in common)
        ph = ", ".join(["%s"] * len(common))
        sql = f'INSERT INTO logs ({col_list}) VALUES ({ph}) ON CONFLICT (id) DO NOTHING'

        inserted = 0
        batch = []
        for row in lite.execute(f"SELECT {col_list} FROM logs"):
            batch.append(tuple(None if (isinstance(v, str) and v == "") else v for v in row))
            if len(batch) >= 500:
                cur.executemany(sql, batch)
                inserted += cur.rowcount
                pg.commit()
                batch = []
        if batch:
            cur.executemany(sql, batch)
            inserted += cur.rowcount
            pg.commit()
        cur.execute("SELECT COUNT(*) FROM logs")
        print("DONE inserted:", inserted, "total:", cur.fetchone()[0], flush=True)
        phase(3)  # success
        return 0
    except Exception:
        traceback.print_exc()
        phase(5)
        return 1


if __name__ == "__main__":
    sys.exit(main())
