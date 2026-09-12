from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data/db/sports_v45.sqlite"
TABLES = (
    "source_snapshot", "event", "participant", "team", "event_participant",
    "participant_history", "team_history", "match_stats", "availability",
    "pit_replay", "pit_feature_snapshot", "model_state_snapshot", "replay_audit",
)


def table_names(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def columns(con: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [r[1] for r in con.execute(f'PRAGMA {schema}.table_info("{table}")')]


def merge_one(target: sqlite3.Connection, source_path: Path, idx: int) -> None:
    alias = f"src{idx}"
    target.execute(f"ATTACH DATABASE ? AS {alias}", (str(source_path),))
    source_tables = {r[0] for r in target.execute(f"SELECT name FROM {alias}.sqlite_master WHERE type='table'")}
    target_tables = table_names(target)

    for table in TABLES:
        if table not in source_tables:
            continue
        if table not in target_tables:
            # Clone the source table's columns so a partially older DB can still be merged.
            target.execute(f'CREATE TABLE main."{table}" AS SELECT * FROM {alias}."{table}" WHERE 0')
            target_tables.add(table)
        src_cols = columns(target, alias, table)
        dst_cols = columns(target, "main", table)
        common = [c for c in src_cols if c in dst_cols]
        if not common:
            continue
        col_sql = ",".join(f'"{c}"' for c in common)
        target.execute(
            f'INSERT OR REPLACE INTO main."{table}" ({col_sql}) '
            f'SELECT {col_sql} FROM {alias}."{table}"'
        )
    target.execute(f"DETACH DATABASE {alias}")


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

    con = sqlite3.connect(out)
    con.execute("PRAGMA foreign_keys=OFF")
    for i, path in enumerate(inputs, start=1):
        merge_one(con, path, i)
    con.commit()
    con.execute("VACUUM")
    con.close()
    print(f"Merged {len(inputs) + 1} partition database(s) into {out}")


if __name__ == "__main__":
    main()
