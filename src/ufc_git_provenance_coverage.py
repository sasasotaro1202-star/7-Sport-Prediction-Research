from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
import subprocess
import tempfile
import io
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path


UPSTREAM_REPO = "https://github.com/Greco1899/scrape_ufc_stats.git"
UPSTREAM_FILES = ("ufc_fight_stats.csv", "ufc_fight_details.csv")
PARSER_VERSION = "ufc-git-provenance-coverage-v2"
ARCHIVE_REPO = "cinhui/ufc-events-stats"
ARCHIVE_COMMIT = "823361a68e1d15242f6182714a683534e02464be"
ARCHIVE_COMMIT_AT = datetime(2020, 6, 15, 16, 52, 4, tzinfo=timezone.utc)
ARCHIVE_OVERVIEW_URL = (
    "https://raw.githubusercontent.com/cinhui/ufc-events-stats/"
    f"{ARCHIVE_COMMIT}/data_ufcstats/ufc-stats-matches-overview.csv"
)
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


def _norm_person(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().casefold().replace(".", "").split())


def _parse_num(value: str | None) -> float | None:
    try:
        x = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _load_archive_overview(url: str = ARCHIVE_OVERVIEW_URL) -> tuple[str, list[dict]]:
    r = requests.get(url, headers={"User-Agent": "SevenSportResearchEngine/4.5.16"}, timeout=45)
    r.raise_for_status()
    raw = r.text
    rows = list(csv.DictReader(io.StringIO(raw)))
    if not rows:
        raise RuntimeError("archive overview returned zero rows")
    return raw, rows


def _archive_value_index(rows: list[dict]) -> dict[tuple[str, str, str, str], list[dict]]:
    out: dict[tuple[str, str, str, str], list[dict]] = {}
    for row in rows:
        date = str(row.get("Date") or "").strip()[:10]
        event = _norm_event(row.get("Event"))
        f1 = _norm_person(row.get("Fighter_1"))
        f2 = _norm_person(row.get("Fighter_2"))
        if not date or not event or not f1 or not f2:
            continue
        key = (date, event, *sorted((f1, f2)))
        out.setdefault(key, []).append({
            "fighter_1": f1,
            "fighter_2": f2,
            "sig_str_1": _parse_num(row.get("STR_1")),
            "sig_str_2": _parse_num(row.get("STR_2")),
            "takedown_1": _parse_num(row.get("TD_1")),
            "takedown_2": _parse_num(row.get("TD_2")),
        })
    return out


def _db_local_index(con: sqlite3.Connection):
    events = con.execute(
        "SELECT event_id, COALESCE(competition_id,''), event_time_utc FROM event WHERE sport='ufc' AND event_time_utc IS NOT NULL"
    ).fetchall()
    event_index: dict[tuple[str, str], list[str]] = {}
    event_time: dict[str, datetime] = {}
    for eid, name, et in events:
        try:
            dt = _parse_timestamp(str(et))
        except ValueError:
            continue
        event_time[str(eid)] = dt
        event_index.setdefault((dt.date().isoformat(), _norm_event(name)), []).append(str(eid))
    participants: dict[str, dict[str, str]] = {}
    for eid, pid, side in con.execute(
        "SELECT event_id, participant_id, side FROM event_participant WHERE event_id IN (SELECT event_id FROM event WHERE sport='ufc') AND side IN ('A','B')"
    ):
        participants.setdefault(str(eid), {})[str(side)] = str(pid)
    names = {str(pid): _norm_person(name) for pid, name in con.execute(
        "SELECT participant_id, canonical_name FROM participant WHERE sport='ufc'"
    )}
    stats: dict[tuple[str, str, str], set[float]] = {}
    for eid, pid, stat, value in con.execute(
        "SELECT event_id, participant_id, stat_name, value_num FROM match_stats WHERE sport='ufc' AND stat_name IN ('sig_str','takedown') AND participant_id IS NOT NULL AND value_num IS NOT NULL"
    ):
        stats.setdefault((str(eid), str(pid), str(stat)), set()).add(float(value))
    return event_index, event_time, participants, names, stats


def _value_equivalence(con: sqlite3.Connection, archive_rows: list[dict]) -> dict:
    event_index, event_time, participants, names, stats = _db_local_index(con)
    archive = _archive_value_index(archive_rows)
    exact = 0
    exact_events: set[str] = set()
    evidence: dict[tuple[str, str], list[datetime]] = {}
    checked = 0
    for (date, event_name, _a, _b), source_rows in archive.items():
        for eid in event_index.get((date, event_name), []):
            checked += 1
            side_to_name = {side: names.get(pid, "") for side, pid in participants.get(eid, {}).items()}
            for row in source_rows:
                for idx, side in ((1, "A"), (2, "B")):
                    src_name = row[f"fighter_{idx}"]
                    pid = next((p for p, nm in side_to_name.items() if nm == src_name), None)
                    if pid is None:
                        continue
                    for stat, field in (("sig_str", f"sig_str_{idx}"), ("takedown", f"takedown_{idx}")):
                        value = row[field]
                        if value is None:
                            continue
                        vals = stats.get((eid, pid, stat), set())
                        if any(abs(v - value) <= 1e-9 for v in vals):
                            exact += 1
                            exact_events.add(eid)
                            evidence.setdefault((pid, stat), []).append(event_time[eid])

    target_events = 0
    candidate_events = 0
    for eid, et in event_time.items():
        cutoff = et - timedelta(minutes=MIN_PIT_GAP_MINUTES)
        if cutoff <= ARCHIVE_COMMIT_AT:
            continue
        candidate_events += 1
        pids = list(participants.get(eid, {}).values())
        if len(pids) != 2:
            continue
        ok_sides = 0
        for pid in pids:
            ok = any(
                any(hist_et < et and hist_et <= cutoff for hist_et in times)
                for (epid, _stat), times in evidence.items()
                if epid == pid
            )
            ok_sides += int(ok)
        if ok_sides == 2:
            target_events += 1
    return {
        "archive_repo": ARCHIVE_REPO,
        "archive_commit": ARCHIVE_COMMIT,
        "archive_commit_at_utc": ARCHIVE_COMMIT_AT.isoformat(),
        "archive_rows": int(len(archive_rows)),
        "local_event_join_candidates_checked": int(checked),
        "exact_local_stat_value_matches": int(exact),
        "exact_local_event_ids": int(len(exact_events)),
        "candidate_target_events_after_archive_snapshot": int(candidate_events),
        "potential_target_events_with_both_sides_historical_evidence": int(target_events),
        "matched_stat_names": ["sig_str", "takedown"],
        "status": "VALUE_EQUIVALENCE_ESTIMATE_ONLY",
    }


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
    current_event_rows = len(events)
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
        "potential_gain_in_event_count": max(0, potential_events - current_event_rows),
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
            archive_raw, archive_rows = _load_archive_overview()
            result["fixed_archive_value_equivalence"] = _value_equivalence(con, archive_rows)
            result["archive_content_sha256"] = hashlib.sha256(
                archive_raw.encode("utf-8", "ignore")
            ).hexdigest()
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
