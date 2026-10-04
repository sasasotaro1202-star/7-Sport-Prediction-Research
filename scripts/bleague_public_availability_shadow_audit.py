from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from src.bleaguer_git_provenance import (
    SUMMARY_NUMERIC_FIELDS,
    match_summary_revision,
    stable_bleaguer_event_id,
    summary_targets_from_bytes,
)

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
EVIDENCE = ROOT / "results/research/bleague_public_availability_evidence.json"
OUT = ROOT / "results/research/bleague_public_availability_shadow_audit.json"

OWNER = "rintaromasuda"
REPO = "bleaguer"
BRANCH = "master"
SEASON = "202021"
PATH = f"inst/extdata/games_summary_{SEASON}.csv"
CURRENT_URL = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{PATH}"
UA = "SevenSportResearchEngine/BLEAGUE-Availability-Shadow-Audit"

STAT_MAP = {
    "PTS": "points",
    "TR": "rebounds",
    "AS": "assists",
    "ST": "steals",
    "BS": "blocks",
    "TO": "turnovers",
    "F2GM": "fieldGoalMade",
    "F2GA": "fieldGoalAttempted",
    "F3GM": "threePointMade",
    "F3GA": "threePointAttempted",
    "FTM": "freeThrowMade",
    "FTA": "freeThrowAttempted",
}
DB_STAT_NAMES = tuple(STAT_MAP.values())
EVIDENCE_BOUND = "2021-04-19T23:59:59Z"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fetch_bytes(url: str) -> bytes:
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    last: Exception | None = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            return response.content
        except (requests.RequestException, ValueError) as exc:
            last = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise last or RuntimeError(f"failed to fetch {url}")


def parse_summary_rows(data: bytes) -> dict[str, dict[str, dict[str, float]]]:
    groups: dict[str, dict[str, dict[str, float]]] = {}
    text = data.decode("utf-8-sig", errors="strict")
    for row in csv.DictReader(io.StringIO(text)):
        schedule_key = str(row.get("ScheduleKey") or "").strip()
        team_id = str(row.get("TeamId") or "").strip()
        if not schedule_key or not team_id:
            continue
        values: dict[str, float] = {}
        for field in SUMMARY_NUMERIC_FIELDS:
            raw = str(row.get(field) or "").strip()
            if not raw:
                values = {}
                break
            values[field] = float(raw)
        if len(values) != len(SUMMARY_NUMERIC_FIELDS):
            continue
        groups.setdefault(schedule_key, {})[team_id] = values
    return {
        key: team_rows
        for key, team_rows in groups.items()
        if len(team_rows) == 2
    }


def normalized_vector(values: dict[str, float], fields: tuple[str, ...]) -> tuple[float, ...]:
    return tuple(float(values[field]) for field in fields)


def vectors_match(
    raw_vectors: list[tuple[float, ...]],
    db_vectors: list[tuple[float, ...]],
) -> bool:
    if len(raw_vectors) != len(db_vectors):
        return False
    left = sorted(raw_vectors)
    right = sorted(db_vectors)
    return all(
        math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-9)
        for av, bv in zip(left, right)
        for a, b in zip(av, bv)
    )


def load_evidence() -> dict:
    data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    rev = data.get("revision_evidence") or {}
    bound = rev.get("public_availability_bound") or {}
    assert data.get("strict_pit_usable") is False
    assert data.get("status") == "RESEARCH_EVIDENCE_ONLY"
    assert rev.get("revision_sha") == "42c621a5437228a4d5a796f62116bee5cc44dce2"
    assert rev.get("next_file_touch_sha") == "64cba9d4693646b3365805da04ad9f8779e5233c"
    assert bound.get("latest_safe_utc") == EVIDENCE_BOUND
    return data


def db_feature_vectors(con: sqlite3.Connection, event_id: str) -> dict | None:
    rows = con.execute(
        f"""SELECT participant_id, stat_name, value_num, effective_at_utc,
                    quality_status, source, source_url
               FROM match_stats
              WHERE sport='basketball'
                AND event_id=?
                AND source='bleaguer-github'
                AND source_url LIKE '%games_summary_{SEASON}.csv'
                AND stat_name IN ({','.join('?' for _ in DB_STAT_NAMES)})""",
        (event_id, *DB_STAT_NAMES),
    ).fetchall()

    grouped: dict[str, dict[str, float]] = {}
    effective_times: list[str] = []
    for participant_id, stat_name, value_num, effective_at, quality_status, source, source_url in rows:
        # Historical B.LEAGUE backfill intentionally keeps source timing
        # unproven, so match_stats rows are normally UNVERIFIABLE. The shadow
        # audit may inspect those rows for exact value agreement, but this never
        # upgrades their PIT/quality status.
        if not participant_id or quality_status not in {"VERIFIED", "UNVERIFIABLE"}:
            return None
        if value_num is None or not math.isfinite(float(value_num)):
            return None
        bucket = grouped.setdefault(str(participant_id), {})
        if stat_name in bucket:
            return None
        bucket[str(stat_name)] = float(value_num)
        if effective_at:
            effective_times.append(str(effective_at))

    if len(grouped) != 2 or any(len(values) != len(DB_STAT_NAMES) for values in grouped.values()):
        return None

    vectors = [
        tuple(values[name] for name in DB_STAT_NAMES)
        for values in grouped.values()
    ]
    return {
        "vectors": sorted(vectors),
        "participant_ids": sorted(grouped),
        "max_effective_at_utc": max(effective_times) if effective_times else None,
    }


def target_team_ids(con: sqlite3.Connection, event_id: str) -> set[str]:
    rows = con.execute(
        """SELECT team_id
             FROM event_participant
            WHERE event_id=?
              AND side IN ('A','B')
              AND team_id IS NOT NULL""",
        (event_id,),
    ).fetchall()
    return {str(row[0]) for row in rows if row[0]}


def audit_db(
    con: sqlite3.Connection,
    exact_rows: dict[str, dict[str, dict[str, float]]],
    matched_schedule_keys: set[str],
    bound: datetime,
) -> dict:
    matched_events_present = 0
    exact_feature_vector_events = 0
    exact_feature_stat_rows = 0
    unresolved_db_events: list[str] = []
    feature_events: dict[str, dict] = {}
    for schedule_key in sorted(matched_schedule_keys):
        event_id = stable_bleaguer_event_id(schedule_key)
        event = con.execute(
            """SELECT event_time_utc, competition_id, season, stage, round, event_type
                 FROM event
                WHERE event_id=?
                  AND sport='basketball'""",
            (event_id,),
        ).fetchone()
        if not event:
            unresolved_db_events.append(schedule_key)
            continue
        matched_events_present += 1
        db_info = db_feature_vectors(con, event_id)
        raw_team_vectors = {
            team_id: normalized_vector(values, SUMMARY_NUMERIC_FIELDS)
            for team_id, values in exact_rows[schedule_key].items()
        }
        raw_vectors = list(raw_team_vectors.values())
        teamwise_match = bool(db_info) and vectors_match(raw_vectors, db_info["vectors"])
        if teamwise_match:
            exact_feature_vector_events += 1
            exact_feature_stat_rows += len(raw_vectors) * len(DB_STAT_NAMES)
            feature_events[event_id] = {
                "event_id": event_id,
                "schedule_key": schedule_key,
                "event_time_utc": event[0],
                "competition_id": event[1],
                "season": event[2],
                "team_ids": sorted(target_team_ids(con, event_id)),
            }

    target_rows = con.execute(
        """SELECT event_id, event_time_utc
             FROM event
            WHERE sport='basketball'
              AND competition_id='B.LEAGUE'
              AND event_time_utc IS NOT NULL
              AND status NOT IN ('CANCELLED','VOID')"""
    ).fetchall()

    cutoff_eligible_targets = 0
    any_history_targets = 0
    both_team_history_targets = 0
    history_observations = 0
    target_details: list[dict] = []

    for event_id, event_time in target_rows:
        try:
            target_time = parse_dt(event_time)
        except Exception:
            continue
        cutoff = target_time - timedelta(minutes=60)
        if cutoff < bound:
            continue
        cutoff_eligible_targets += 1
        teams = target_team_ids(con, event_id)
        prior = []
        teams_with_history: set[str] = set()
        for feature_event in feature_events.values():
            try:
                feature_time = parse_dt(feature_event["event_time_utc"])
            except Exception:
                continue
            if feature_time <= cutoff:
                prior.append(feature_event["event_id"] if "event_id" in feature_event else feature_event["schedule_key"])
                teams_with_history.update(teams.intersection(feature_event["team_ids"]))
        history_count = len(prior)
        history_observations += history_count
        has_any = bool(prior) and bool(teams_with_history)
        has_both = len(teams) >= 2 and teams.issubset(teams_with_history)
        any_history_targets += int(has_any)
        both_team_history_targets += int(has_both)
        if len(target_details) < 200:
            target_details.append({
                "event_id": event_id,
                "event_time_utc": event_time,
                "cutoff_at_utc": cutoff.isoformat(),
                "target_team_count": len(teams),
                "prior_exact_feature_event_count": history_count,
                "target_teams_with_history": len(teams_with_history),
                "both_target_teams_have_history": has_both,
            })

    return {
        "matched_events_present_in_db": matched_events_present,
        "exact_feature_vector_events": exact_feature_vector_events,
        "exact_feature_stat_rows": exact_feature_stat_rows,
        "matched_events_missing_from_db": len(unresolved_db_events),
        "matched_events_missing_schedule_keys": unresolved_db_events[:100],
        "candidate_target_events_total": len(target_rows),
        "identity_scope": "canonical_schedule_key_event_identity; two-team vector matching is side-agnostic",
        "candidate_target_events_cutoff_at_or_after_bound": cutoff_eligible_targets,
        "candidate_targets_with_any_exact_history": any_history_targets,
        "candidate_targets_with_both_team_exact_history": both_team_history_targets,
        "candidate_prior_history_observations": history_observations,
        "target_detail_sample": target_details,
    }


def main() -> int:
    generated_at = utcnow()
    evidence = load_evidence()
    revision_sha = evidence["revision_evidence"]["revision_sha"]
    bound = parse_dt(EVIDENCE_BOUND)

    if not DB.is_file() or DB.stat().st_size <= 0:
        raise SystemExit("SHADOW_AUDIT_DB_MISSING")

    current_bytes = _fetch_bytes(CURRENT_URL)
    pinned_url = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{revision_sha}/{PATH}"
    pinned_bytes = _fetch_bytes(pinned_url)

    targets = summary_targets_from_bytes(current_bytes)
    matched = match_summary_revision(pinned_bytes, targets, set(targets))
    exact_rows = parse_summary_rows(pinned_bytes)
    matched = {
        key: value
        for key, value in matched.items()
        if key in exact_rows and len(exact_rows[key]) == 2
    }

    with sqlite3.connect(DB) as con:
        db_report = audit_db(con, exact_rows, set(matched), bound)

    report = {
        "version": "bleague-public-availability-shadow-audit-v1",
        "status": "SHADOW_AUDIT_COMPLETED",
        "generated_at_utc": generated_at,
        "git_head": __import__("os").environ.get("GITHUB_SHA", "UNKNOWN"),
        "scope": {
            "sport": "basketball",
            "competition": "B.LEAGUE",
            "season_file": PATH,
            "prediction_cutoff_policy": "T-60",
        },
        "evidence": {
            "status": evidence["status"],
            "strict_pit_usable": evidence["strict_pit_usable"],
            "revision_sha": revision_sha,
            "pinned_source_url": pinned_url,
            "current_source_url": CURRENT_URL,
            "pinned_content_sha256": hashlib.sha256(pinned_bytes).hexdigest(),
            "current_content_sha256": hashlib.sha256(current_bytes).hexdigest(),
            "matched_current_rows_in_pinned_revision": len(matched),
            "public_availability_bound_utc": EVIDENCE_BOUND,
            "next_file_touch_sha": evidence["revision_evidence"]["next_file_touch_sha"],
            "next_file_touch_timestamp_utc": evidence["revision_evidence"]["next_file_touch_timestamp_utc"],
        },
        "candidate_pit": db_report,
        "safety": {
            "database_mutation": False,
            "source_snapshot_promotion": False,
            "match_stats_repoint": False,
            "production_model_change": False,
            "route_change": False,
            "probability_change": False,
            "holdout_change": False,
            "strict_pit_acceptance_change": False,
            "promotion_allowed": False,
        },
        "interpretation": (
            "This is a research-only shadow audit. An event is counted as an exact "
            "feature event only when the current 2020-21 summary row pair is present "
            "unchanged in the pinned 2021-04-13 Git revision and the current database "
            "contains the corresponding two-team 12-stat feature vectors from the "
            "same corpus. Candidate target coverage applies the conservative public-"
            "availability bound only to T-60 cutoffs at or after that bound."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
