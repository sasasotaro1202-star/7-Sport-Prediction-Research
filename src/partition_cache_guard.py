from __future__ import annotations
import argparse
import json
import sqlite3
from pathlib import Path

REQUIRED = {"event", "participant", "event_participant", "source_snapshot"}
SPORTS = {"valorant", "basketball", "volleyball", "tennis", "ufc", "rizin", "f1"}


def source_count_for_sport(con: sqlite3.Connection, sport: str) -> int:
    cols = {r[1] for r in con.execute("PRAGMA table_info(source_snapshot)")}
    if "sport" in cols:
        return int(con.execute("SELECT COUNT(*) FROM source_snapshot WHERE sport=?", (sport,)).fetchone()[0])
    if "provenance_json" not in cols:
        return 0
    count = 0
    for (payload,) in con.execute("SELECT provenance_json FROM source_snapshot"):
        if not payload:
            continue
        try:
            if json.loads(payload).get("sport") == sport:
                count += 1
        except Exception:
            continue
    return count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--sport", required=True, choices=sorted(SPORTS))
    args = ap.parse_args()
    p = Path(args.db)
    if not p.is_file() or p.stat().st_size == 0:
        print(f"CACHE_GUARD=FAIL sport={args.sport} reason=missing_or_empty")
        return 2
    con = None
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
        events = int(con.execute("SELECT COUNT(*) FROM event WHERE sport=?", (args.sport,)).fetchone()[0])
        participants = int(con.execute("SELECT COUNT(*) FROM participant WHERE sport=?", (args.sport,)).fetchone()[0])
        snapshots = source_count_for_sport(con, args.sport)
        timed = int(con.execute("SELECT COUNT(*) FROM event WHERE sport=? AND event_time_utc IS NOT NULL", (args.sport,)).fetchone()[0])
        if events <= 0 or snapshots <= 0:
            print(f"CACHE_GUARD=FAIL sport={args.sport} reason=empty_partition events={events} snapshots={snapshots} participants={participants} timed_events={timed}")
            return 2
        print(f"CACHE_GUARD=PASS sport={args.sport} events={events} snapshots={snapshots} participants={participants} timed_events={timed} size={p.stat().st_size}")
        return 0
    except Exception as exc:
        print(f"CACHE_GUARD=FAIL sport={args.sport} reason={type(exc).__name__}:{exc}")
        return 2
    finally:
        if con is not None:
            con.close()


if __name__ == "__main__":
    raise SystemExit(main())
