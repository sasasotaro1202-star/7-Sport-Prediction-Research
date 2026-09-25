from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


UPSTREAM_REPO = "https://github.com/Greco1899/scrape_ufc_stats.git"
UPSTREAM_FILES = ("ufc_fight_stats.csv", "ufc_fight_details.csv")
PARSER_VERSION = "ufc-git-provenance-coverage-v1"
MIN_PIT_GAP_MINUTES = 60


def _run(args: list[str], cwd: Path | None = None) -> str:
    p = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return p.stdout


def _norm_event(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().casefold().split())


def _parse_timestamp(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _added_event_names(diff_text: str) -> set[str]:
    out: set[str] = set()
    current_file = None
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[6:].strip()
            continue
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        if current_file not in UPSTREAM_FILES:
            continue
        line = raw[1:]
        try:
            row = next(csv.reader([line]))
        except Exception:
            continue
        if not row:
            continue
        event = row[0].strip()
        if not event or event == "EVENT":
            continue
        out.add(event)
    return out


def collect_first_seen(repo_dir: Path) -> tuple[dict[str, datetime], dict[str, str], int]:
    fmt = "%H%x09%cI"
    logs = _run(
        ["git", "log", "--reverse", f"--format={fmt}", "--", *UPSTREAM_FILES],
        cwd=repo_dir,
    )
    first_seen: dict[str, datetime] = {}
    first_commit: dict[str, str] = {}
    commit_rows = 0

    for item in logs.splitlines():
        if not item.strip():
            continue
        try:
            sha, created = item.split("\t", 1)
            commit_time = _parse_timestamp(created)
        except ValueError:
            continue
        commit_rows += 1
        diff = _run(
            [
                "git",
                "show",
                "--format=",
                "--unified=0",
                "--diff-filter=AM",
                sha,
                "--",
                *UPSTREAM_FILES,
            ],
            cwd=repo_dir,
        )
        for event in _added_event_names(diff):
            key = _norm_event(event)
            if key and key not in first_seen:
                first_seen[key] = commit_time
                first_commit[key] = sha

    return first_seen, first_commit, commit_rows


def _db_events(con: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return list(
        con.execute(
            """
            SELECT event_id, COALESCE(competition_id, ''), event_time_utc
              FROM event
             WHERE sport='ufc'
               AND event_time_utc IS NOT NULL
             ORDER BY event_time_utc, event_id
            """
        )
    )


def _db_stat_counts(con: sqlite3.Connection) -> dict[str, int]:
    rows = con.execute(
        """
        SELECT e.event_id, COUNT(*)
          FROM match_stats ms
          JOIN event e ON e.event_id=ms.event_id
         WHERE ms.sport='ufc'
         GROUP BY e.event_id
        """
    ).fetchall()
    return {str(eid): int(n) for eid, n in rows}


def evaluate_coverage(
    con: sqlite3.Connection,
    first_seen: dict[str, datetime],
    first_commit: dict[str, str],
) -> dict:
    events = _db_events(con)
    stat_counts = _db_stat_counts(con)

    matched = 0
    potential_events = 0
    potential_stats_rows = 0
    uncovered: list[dict] = []
    covered: list[dict] = []

    for event_id, name, event_time in events:
        key = _norm_event(name)
        seen = first_seen.get(key)
        if seen is None:
            uncovered.append(
                {
                    "event_id": event_id,
                    "event_name": name,
                    "event_time_utc": event_time,
                    "reason": "upstream_event_not_seen_in_git_history",
                }
            )
            continue
        matched += 1
        cutoff = _parse_timestamp(event_time)
        pit_cutoff = cutoff.timestamp() - MIN_PIT_GAP_MINUTES * 60
        if seen.timestamp() <= pit_cutoff:
            potential_events += 1
            stat_rows = stat_counts.get(event_id, 0)
            potential_stats_rows += stat_rows
            covered.append(
                {
                    "event_id": event_id,
                    "event_name": name,
                    "event_time_utc": event_time,
                    "source_available_at_utc": seen.isoformat(),
                    "source_commit": first_commit[key],
                    "current_match_stats_rows": stat_rows,
                }
            )
        else:
            uncovered.append(
                {
                    "event_id": event_id,
                    "event_name": name,
                    "event_time_utc": event_time,
                    "source_available_at_utc": seen.isoformat(),
                    "source_commit": first_commit[key],
                    "reason": "upstream_first_seen_after_pit_cutoff",
                }
            )

    strict_rows = con.execute(
        """
        SELECT COUNT(*)
          FROM pit_replay
         WHERE replay_status='REPLAYABLE'
           AND leakage_status='CLEAN'
           AND event_id IN (SELECT event_id FROM event WHERE sport='ufc')
        """
    ).fetchone()[0]

    return {
        "parser_version": PARSER_VERSION,
        "upstream_repo": "Greco1899/scrape_ufc_stats",
        "upstream_files": list(UPSTREAM_FILES),
        "git_commit_history_rows_scanned": None,
        "db_ufc_event_rows": len(events),
        "matched_event_names": matched,
        "potential_pit_covered_events": potential_events,
        "potential_current_match_stats_rows": potential_stats_rows,
        "current_strict_replayable_rows": int(strict_rows),
        "potential_gain_in_event_count": max(0, potential_events - int(strict_rows)),
        "methodology": (
            "Research-only coverage estimate. An upstream event is considered "
            "potentially PIT-usable when its first observed addition to the "
            "tracked UFCStats CSV history is at least 60 minutes before the "
            "event cutoff. This report does not mutate the database and does "
            "not certify row-value equivalence to the local dataset."
        ),
        "covered_sample": covered[:20],
        "uncovered_sample": uncovered[:20],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/db/sports_v45.sqlite")
    ap.add_argument("--output", default="results/ufc_git_provenance_coverage.json")
    ap.add_argument("--repo-url", default=UPSTREAM_REPO)
    args = ap.parse_args()

    db_path = Path(args.db)
    out_path = Path(args.output)
    if not db_path.is_file():
        raise SystemExit(f"FAIL_CLOSED_DB_MISSING:{db_path}")

    temp_root = Path(tempfile.mkdtemp(prefix="ufc-prov-"))
    repo_dir = temp_root / "upstream"
    try:
        _run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                args.repo_url,
                str(repo_dir),
            ]
        )
        first_seen, first_commit, commit_rows = collect_first_seen(repo_dir)
        with sqlite3.connect(db_path) as con:
            result = evaluate_coverage(con, first_seen, first_commit)
        result["git_commit_history_rows_scanned"] = int(commit_rows)
        result["unique_upstream_event_names_seen"] = int(len(first_seen))
        result["status"] = "ESTIMATE_ONLY"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
