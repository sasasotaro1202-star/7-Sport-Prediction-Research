from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.storage.db_v45 import utcnow


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data/db/sports_v45.sqlite"
ARCHIVE_REPO = "cinhui/ufc-events-stats"
ARCHIVE_COMMIT = "823361a68e1d15242f6182714a683534e02464be"
ARCHIVE_COMMIT_AT = "2020-06-15T16:52:04+00:00"
ARCHIVE_URL = (
    "https://raw.githubusercontent.com/cinhui/ufc-events-stats/"
    f"{ARCHIVE_COMMIT}/data_ufcstats/ufc-stats-matches-overview.csv"
)
PARSER_VERSION = "ufc-fixed-archive-backfill-v1"


def _norm(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().casefold().replace(".", "").split())


def _iso_date(value: str | None) -> str:
    return str(value or "").strip()[:10]


def _num(value: str | None) -> float | None:
    try:
        x = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def fetch_archive() -> tuple[str, list[dict]]:
    r = requests.get(
        ARCHIVE_URL,
        headers={"User-Agent": "SevenSportResearchEngine/4.5.16"},
        timeout=45,
    )
    r.raise_for_status()
    raw = r.text
    rows = list(csv.DictReader(io.StringIO(raw)))
    if not rows:
        raise RuntimeError("archive returned zero rows")
    return raw, rows


def load_local_maps(con: sqlite3.Connection):
    event_map: dict[tuple[str, str], list[str]] = {}
    for eid, competition, event_time in con.execute(
        """
        SELECT event_id, COALESCE(competition_id,''), event_time_utc
          FROM event
         WHERE sport='ufc' AND event_time_utc IS NOT NULL
        """
    ):
        event_map.setdefault(
            (_iso_date(event_time), _norm(competition)),
            [],
        ).append(str(eid))

    participant_map: dict[str, list[str]] = {}
    for pid, name in con.execute(
        "SELECT participant_id, canonical_name FROM participant WHERE sport='ufc'"
    ):
        participant_map.setdefault(_norm(name), []).append(str(pid))

    event_participants: dict[str, dict[str, str]] = {}
    for eid, pid, side in con.execute(
        """
        SELECT event_id, participant_id, side
          FROM event_participant
         WHERE side IN ('A','B')
           AND event_id IN (SELECT event_id FROM event WHERE sport='ufc')
        """
    ):
        event_participants.setdefault(str(eid), {})[str(side)] = str(pid)

    event_times = {
        str(eid): str(event_time)
        for eid, event_time in con.execute(
            "SELECT event_id, event_time_utc FROM event WHERE sport='ufc' AND event_time_utc IS NOT NULL"
        )
    }
    pid_to_name = {
        str(pid): name
        for name, pids in participant_map.items()
        for pid in pids
    }
    return event_map, participant_map, event_participants, event_times, pid_to_name


def upsert_snapshot(
    con: sqlite3.Connection,
    content_hash: str,
) -> str:
    snapshot_id = hashlib.sha256(
        f"{ARCHIVE_REPO}|{ARCHIVE_COMMIT}|{content_hash}".encode()
    ).hexdigest()[:32]
    con.execute(
        """
        INSERT OR REPLACE INTO source_snapshot(
            snapshot_id, source, source_url, retrieved_at_utc,
            source_available_at_utc, event_time_utc, content_hash,
            parser_version, availability_status, provenance_json
        )
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            snapshot_id,
            ARCHIVE_REPO,
            ARCHIVE_URL,
            utcnow(),
            ARCHIVE_COMMIT_AT,
            None,
            content_hash,
            PARSER_VERSION,
            "EXACT",
            json.dumps(
                {
                    "repository": ARCHIVE_REPO,
                    "commit": ARCHIVE_COMMIT,
                    "commit_time_utc": ARCHIVE_COMMIT_AT,
                    "availability_basis": "public_git_commit_timestamp",
                    "scope": "fixed historical archive content",
                    "non_claim": "commit time proves repository snapshot existence, not an exact original web-publication time",
                },
                ensure_ascii=False,
            ),
        ),
    )
    return snapshot_id


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument(
        "--output",
        default=str(ROOT / "results/ufc_fixed_archive_backfill.json"),
    )
    args = ap.parse_args()

    db = Path(args.db)
    if not db.is_file():
        raise SystemExit(f"FAIL_CLOSED_DB_MISSING:{db}")

    raw, rows = fetch_archive()
    content_hash = hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()

    with sqlite3.connect(db) as con:
        event_map, participant_map, event_participants, event_times, pid_to_name = load_local_maps(con)
        snapshot_id = upsert_snapshot(con, content_hash)

        matched_rows = 0
        unmatched_events = 0
        unmatched_participants = 0
        inserted_stats = 0
        skipped_missing_values = 0
        touched_events: set[str] = set()

        for row in rows:
            date = _iso_date(row.get("Date"))
            event_name = _norm(row.get("Event"))
            f1 = _norm(row.get("Fighter_1"))
            f2 = _norm(row.get("Fighter_2"))
            if not date or not event_name or not f1 or not f2:
                continue

            event_ids = event_map.get((date, event_name), [])
            if not event_ids:
                unmatched_events += 1
                continue

            # Deterministic matching: require exactly one local event.
            if len(event_ids) != 1:
                unmatched_events += 1
                continue
            eid = event_ids[0]
            matched_rows += 1

            local_sides = event_participants.get(eid, {})
            side_pid: dict[str, str] = {}
            for side in ("A", "B"):
                pid = local_sides.get(side)
                expected_name = f1 if side == "A" else f2
                if pid and pid_to_name.get(pid) == expected_name:
                    side_pid[side] = pid

            if "A" not in side_pid or "B" not in side_pid:
                # Fallback to exact canonical-name matching, but never fuzzy-match.
                a_candidates = participant_map.get(f1, [])
                b_candidates = participant_map.get(f2, [])
                if len(a_candidates) == 1 and len(b_candidates) == 1:
                    side_pid["A"] = a_candidates[0]
                    side_pid["B"] = b_candidates[0]

            if "A" not in side_pid or "B" not in side_pid:
                unmatched_participants += 1
                continue

            for side, pid, field in (
                ("A", side_pid["A"], "STR_1"),
                ("B", side_pid["B"], "STR_2"),
            ):
                value = _num(row.get(field))
                if value is None:
                    skipped_missing_values += 1
                    continue
                stat_id = hashlib.sha256(
                    f"ufc-fixed|{eid}|{pid}|sig_str|{value}".encode()
                ).hexdigest()[:32]
                event_time = event_times[eid]
                con.execute(
                    """
                    INSERT OR REPLACE INTO match_stats(
                        stat_id,event_id,participant_id,team_id,sport,
                        observed_at_utc,effective_at_utc,stat_name,
                        value_num,value_text,unit,source,source_url,
                        quality_status,confidence
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        stat_id,
                        eid,
                        pid,
                        None,
                        "ufc",
                        utcnow(),
                        event_time,
                        "sig_str",
                        value,
                        str(value),
                        None,
                        ARCHIVE_REPO,
                        ARCHIVE_URL,
                        "EXACT",
                        1.0,
                    ),
                )
                inserted_stats += 1
                touched_events.add(eid)

            for side, pid, field in (
                ("A", side_pid["A"], "TD_1"),
                ("B", side_pid["B"], "TD_2"),
            ):
                value = _num(row.get(field))
                if value is None:
                    skipped_missing_values += 1
                    continue
                stat_id = hashlib.sha256(
                    f"ufc-fixed|{eid}|{pid}|takedown|{value}".encode()
                ).hexdigest()[:32]
                event_time = con.execute(
                    "SELECT event_time_utc FROM event WHERE event_id=?",
                    (eid,),
                ).fetchone()[0]
                con.execute(
                    """
                    INSERT OR REPLACE INTO match_stats(
                        stat_id,event_id,participant_id,team_id,sport,
                        observed_at_utc,effective_at_utc,stat_name,
                        value_num,value_text,unit,source,source_url,
                        quality_status,confidence
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        stat_id,
                        eid,
                        pid,
                        None,
                        "ufc",
                        utcnow(),
                        event_time,
                        "takedown",
                        value,
                        str(value),
                        None,
                        ARCHIVE_REPO,
                        ARCHIVE_URL,
                        "EXACT",
                        1.0,
                    ),
                )
                inserted_stats += 1
                touched_events.add(eid)

        con.commit()

        before = int(
            con.execute(
                """
                SELECT COUNT(*) FROM pit_replay
                 WHERE replay_status='REPLAYABLE'
                   AND leakage_status='CLEAN'
                   AND event_id IN (SELECT event_id FROM event WHERE sport='ufc')
                """
            ).fetchone()[0]
        )

        report = {
            "status": "RESEARCH_DB_ONLY",
            "archive_repo": ARCHIVE_REPO,
            "archive_commit": ARCHIVE_COMMIT,
            "archive_commit_at_utc": ARCHIVE_COMMIT_AT,
            "archive_content_sha256": content_hash,
            "archive_rows": len(rows),
            "matched_archive_rows_to_unique_local_events": matched_rows,
            "unmatched_events": unmatched_events,
            "unmatched_participants": unmatched_participants,
            "inserted_stat_rows": inserted_stats,
            "skipped_missing_values": skipped_missing_values,
            "touched_local_events": len(touched_events),
            "strict_replayable_rows_before": before,
            "snapshot_id": snapshot_id,
            "production_model_changed": False,
            "provenance_status": "EXACT_FIXED_GIT_SNAPSHOT",
            "caution": "The commit timestamp is treated as the conservative availability bound for this fixed public repository snapshot; no claim is made about the original UFCStats web publication time.",
        }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
