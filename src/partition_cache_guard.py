from __future__ import annotations
import argparse
import sqlite3
from pathlib import Path

REQUIRED = {"event", "participant", "event_participant", "source_snapshot"}
SPORTS = {"valorant", "basketball", "volleyball", "tennis", "ufc", "rizin", "f1"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--sport", required=True, choices=sorted(SPORTS))
    args = ap.parse_args()
    p = Path(args.db)
    if not p.is_file() or p.stat().st_size == 0:
        print(f"CACHE_GUARD=FAIL sport={args.sport} reason=missing_or_empty")
        return 2
    try:
        con = sqlite3.connect(f"file:{p.resolve()}?mode=ro", uri=True)
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            print(f"CACHE_GUARD=FAIL sport={args.sport} reason=integrity:{integrity}")
            return 2
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        missing = sorted(REQUIRED - tables)
        if missing:
            print(f"CACHE_GUARD=FAIL sport={args.sport} reason=missing_tables:{','.join(missing)}")
            return 2
        n = int(con.execute("select count(*) from event where sport=?", (args.sport,)).fetchone()[0])
        snapshots = int(con.execute("select count(*) from source_snapshot where sport=?", (args.sport,)).fetchone()[0])
        if n <= 0 or snapshots <= 0:
            print(f"CACHE_GUARD=FAIL sport={args.sport} reason=empty_partition events={n} snapshots={snapshots}")
            return 2
        print(f"CACHE_GUARD=PASS sport={args.sport} events={n} snapshots={snapshots} size={p.stat().st_size}")
        return 0
    except Exception as exc:
        print(f"CACHE_GUARD=FAIL sport={args.sport} reason={type(exc).__name__}:{exc}")
        return 2
    finally:
        try:
            con.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
