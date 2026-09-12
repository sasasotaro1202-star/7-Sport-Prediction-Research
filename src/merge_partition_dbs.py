from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data/db/sports_v45.sqlite"
TABLES = (
    "source_snapshot",
    "event",
    "participant",
    "team",
    "event_participant",
    "participant_history",
    "team_history",
    "match_stats",
    "availability",
    "pit_replay",
    "pit_feature_snapshot",
    "model_state_snapshot",
    "replay_audit",
)


def tables(con: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def merge_one(target: sqlite3.Connection, source_path: Path, idx: int) -> dict[str, int]:
    alias = f"src{idx}"
    target.execute(f"ATTACH DATABASE ? AS {alias}", (str(source_path),))
    source_tables = tables(target.execute(f"SELECT 1 FROM {alias}.sqlite_master LIMIT 0") if False else sqlite3.connect(source_path))
    # Re-open metadata connection above only for a small schema check.
    target.connection  # keep linters quiet on older sqlite wrappers
    counts: dict[str, int] = {}
    for table in TABLES:
        if table not in source_tables:
            continue
        cols = [r[1] for r in target.execute(f"PRAGMA table_info({table})")]
        if not cols:
            continue
        col_sql = ",".join(f'"{c}"' for c in cols)
        target.execute(
            f'INSERT OR REPLACE INTO main."{table}" ({col_sql}) '
            f'SELECT {col_sql} FROM {alias}."{table}"'
        )
        counts[table] = target.execute(f'SELECT changes()').fetchone()[0]
    target.execute(f"DETACH DATABASE {alias}")
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", default="bootstrap-artifacts")
    ap.add_argument("--output", default=str(DEFAULT_DB))
    args = ap.parse_args()

    inputs = sorted(Path(args.input_dir).rglob("sports_v45.sqlite"))
    if not inputs:
        raise SystemExit("No partition databases found")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        shutil.copy2(inputs[0], out)
        inputs = inputs[1:]
        if not inputs:
            print(f"Initialized database from {out}")
            return

    con = sqlite3.connect(out)
    con.execute("PRAGMA foreign_keys=OFF")
    merged = 0
    for i, path in enumerate(inputs, start=1):
        merge_one(con, path, i)
        merged += 1
    con.commit()
    con.execute("VACUUM")
    con.close()
    print(f"Merged {merged} partition database(s) into {out}")


if __name__ == "__main__":
    main()
