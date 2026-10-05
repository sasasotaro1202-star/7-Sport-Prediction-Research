from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
SCOPE = ROOT / "config/PROJECT_SCOPE_POLICY.json"

SPORT_STAT_POLICY = {
    "valorant": ("rating", "acs", "adr", "kast", "k_d", "fk_fd"),
    "basketball": (
        "points", "rebounds", "assists", "steals", "blocks",
        "turnovers", "fieldGoalPct", "threePointPct", "freeThrowPct",
    ),
    "volleyball": ("attack", "serve", "receive", "block", "error", "sideout"),
    "ufc": ("sig_str", "takedown", "td_pct", "sub_attempts", "control_time"),
    "rizin": ("sig_str", "takedown", "td_pct", "sub_attempts", "control_time"),
}

SUM_STATS = {
    "points", "rebounds", "assists", "steals", "blocks", "turnovers",
    "sig_str", "takedown", "sub_attempts", "control_time",
    "attack", "serve", "receive", "block", "error", "sideout",
    "acs", "adr", "fk_fd",
}
RATE_STATS = {
    "fieldGoalPct", "threePointPct", "freeThrowPct", "td_pct", "kast",
    "rating", "k_d",
}
COMPLETED_STATUSES = {"COMPLETED", "FINISHED", "POST", "FINAL"}


def parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if out.tzinfo is None:
        out = out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(x) for x in parts).encode("utf-8")).hexdigest()[:32]


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def active_scope() -> tuple[str, ...]:
    obj = json.loads(SCOPE.read_text(encoding="utf-8"))
    return tuple(str(x) for x in obj.get("active_prediction_scope") or ())


def competition_in_scope(sport: str, competition_id: str | None) -> bool:
    cid = (competition_id or "").lower()
    if sport == "basketball":
        return any(x in cid for x in (
            "b.league", "b league", "bリーグ", "b.premier",
            "b.one", "b.two", "b one", "b two", "asian games", "アジア大会",
        ))
    if sport == "volleyball":
        return any(x in cid for x in ("asian games", "アジア大会"))
    return True


def agg(values: list[float], stat_name: str) -> float:
    if not values:
        return 0.0
    if stat_name in RATE_STATS:
        return float(sum(values) / len(values))
    return float(sum(values))


def source_availability(
    con: sqlite3.Connection,
    source: str | None,
    source_url: str | None,
    event_time_utc: str,
) -> datetime | None:
    if not source or not source_url:
        return None
    row = con.execute(
        """SELECT MIN(source_available_at_utc)
             FROM source_snapshot
            WHERE source=?
              AND source_url=?
              AND availability_status='EXACT'
              AND source_available_at_utc IS NOT NULL
              AND event_time_utc=?
        """,
        (source, source_url, event_time_utc),
    ).fetchone()
    return parse_dt(row[0]) if row and row[0] else None


def collect_event(
    con: sqlite3.Connection,
    sport: str,
    event_id: str,
    sample_minutes: int,
) -> list[dict[str, Any]]:
    event = con.execute(
        """SELECT event_id,competition_id,event_time_utc,event_end_time_utc,status
             FROM event WHERE event_id=? AND sport=?""",
        (event_id, sport),
    ).fetchone()
    if not event:
        return []
    _, competition_id, event_time_raw, event_end_raw, status = event
    if str(status or "").upper() not in COMPLETED_STATUSES:
        return []
    start = parse_dt(event_time_raw)
    end = parse_dt(event_end_raw)
    if start is None or end is None or end <= start:
        return []
    if not competition_in_scope(sport, competition_id):
        return []

    eps = con.execute(
        """SELECT participant_id,team_id,side
             FROM event_participant
            WHERE event_id=? AND side IN ('A','B')
              AND (participant_id IS NOT NULL OR team_id IS NOT NULL)
        """,
        (event_id,),
    ).fetchall()
    if not eps:
        return []
    side_pid: dict[str, str] = {}
    side_team: dict[str, str] = {}
    for pid, team_id, side in eps:
        side = str(side)
        if side not in {"A", "B"}:
            continue
        if pid:
            side_pid[str(pid)] = side
        if team_id:
            side_team[str(team_id)] = side
    if not side_pid and not side_team:
        return []

    stats = SPORT_STAT_POLICY.get(sport, ())
    if not stats or not table_exists(con, "match_stats") or not table_exists(con, "source_snapshot"):
        return []

    placeholders = ",".join("?" for _ in stats)
    rows = con.execute(
        f"""SELECT ms.stat_id,ms.participant_id,ms.team_id,ms.stat_name,
                   ms.value_num,ms.observed_at_utc,ms.effective_at_utc,
                   ms.source,ms.source_url
              FROM match_stats ms
             WHERE ms.event_id=?
               AND ms.sport=?
               AND ms.stat_name IN ({placeholders})
               AND ms.value_num IS NOT NULL
               AND ms.observed_at_utc IS NOT NULL
             ORDER BY ms.observed_at_utc,ms.effective_at_utc,ms.stat_id""",
        (event_id, sport, *stats),
    ).fetchall()
    if not rows:
        return []

    valid = []
    for stat_id, pid, team_id, stat_name, value, observed_raw, effective_raw, source, source_url in rows:
        observed = parse_dt(observed_raw)
        effective = parse_dt(effective_raw) if effective_raw else observed
        if observed is None or effective is None:
            continue
        if not (start <= observed < end):
            continue
        if effective > observed:
            continue
        available = source_availability(con, source, source_url, event_time_raw)
        if available is None or available > observed:
            continue
        side = side_pid.get(str(pid)) if pid else None
        if side is None and team_id:
            side = side_team.get(str(team_id))
        if side not in {"A", "B"}:
            continue
        valid.append({
            "stat_id": str(stat_id),
            "participant_id": str(pid) if pid else None,
            "team_id": str(team_id) if team_id else None,
            "side": side,
            "stat_name": str(stat_name),
            "value": float(value),
            "observed": observed,
            "effective": effective,
            "source_available": available,
        })
    if not valid:
        return []

    by_bin: dict[int, list[dict[str, Any]]] = {}
    for item in valid:
        bin_id = int((item["observed"] - start).total_seconds() // (sample_minutes * 60))
        by_bin.setdefault(bin_id, []).append(item)

    snapshots = []
    for bin_id, items in sorted(by_bin.items()):
        snapshot_time = max(x["observed"] for x in items)
        latest: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in valid:
            if item["observed"] > snapshot_time or item["effective"] > snapshot_time:
                continue
            key = (item["side"], item["stat_name"], item["participant_id"] or f"team:{item['team_id']}")
            previous = latest.get(key)
            if previous is None or (
                item["observed"], item["effective"], item["stat_id"]
            ) > (
                previous["observed"], previous["effective"], previous["stat_id"]
            ):
                if item["source_available"] <= snapshot_time:
                    latest[key] = item

        state: list[float] = []
        max_source_available = start
        for stat_name in stats:
            for side in ("A", "B"):
                vals = [
                    x["value"] for x in latest.values()
                    if x["side"] == side and x["stat_name"] == stat_name
                ]
                state.append(agg(vals, stat_name))
                state.append(1.0 if vals else 0.0)
                for x in latest.values():
                    if x["side"] == side and x["stat_name"] == stat_name:
                        if x["source_available"] > max_source_available:
                            max_source_available = x["source_available"]

        if max_source_available > snapshot_time:
            continue

        state.append(float((snapshot_time - start).total_seconds()))
        feature_vector = list(state)
        snapshot_id = sha(
            "trajectory-v1", sport, event_id, iso(snapshot_time),
            json.dumps(feature_vector, separators=(",", ":")),
        )
        snapshots.append({
            "snapshot_id": snapshot_id,
            "event_id": event_id,
            "sport": sport,
            "event_time_utc": iso(start),
            "event_end_time_utc": iso(end),
            "prediction_time_utc": iso(snapshot_time),
            "source_available_at_utc": iso(max_source_available),
            "feature_vector": feature_vector,
            "observed_state_vector": list(state),
            "state_schema": {
                "version": "generic-stat-state-v1",
                "statistics": list(stats),
                "per_stat_fields": ["value", "present"],
                "aggregation": {
                    "sum_stats": sorted(SUM_STATS.intersection(stats)),
                    "rate_stats": sorted(RATE_STATS.intersection(stats)),
                },
                "elapsed_seconds": True,
            },
            "observation_count": len(latest),
            "bin_minutes": sample_minutes,
        })
    return snapshots


def collect(
    sport: str,
    db_path: Path,
    mode: str = "in_event",
    sample_minutes: int = 5,
) -> dict[str, Any]:
    if mode != "in_event":
        raise ValueError("collector currently supports only the strict in_event trajectory lane")
    if sport not in active_scope():
        return {"status": "BLOCKED", "sport": sport, "reason": "SPORT_OUTSIDE_ACTIVE_SCOPE"}
    if not db_path.is_file() or db_path.stat().st_size <= 0:
        return {"status": "BLOCKED", "sport": sport, "reason": "DATABASE_UNAVAILABLE"}

    con = sqlite3.connect(db_path)
    try:
        if not all(table_exists(con, x) for x in ("event", "event_participant", "match_stats", "source_snapshot", "event_outcome")):
            return {"status": "BLOCKED", "sport": sport, "reason": "REQUIRED_TABLE_MISSING"}
        # Snapshot coverage is independent from final-outcome verification.
        # Unverified outcomes are never used for OOS; they may be attached later.
        event_rows = con.execute(
            """SELECT e.event_id
                 FROM event e
                WHERE e.sport=?
                  AND e.event_time_utc IS NOT NULL
                  AND e.event_end_time_utc IS NOT NULL
                  AND UPPER(e.status) IN ('COMPLETED','FINISHED','POST','FINAL')
                ORDER BY e.event_time_utc,e.event_id""",
            (sport,),
        ).fetchall()
        snapshots: list[dict[str, Any]] = []
        outcomes: dict[str, dict[str, Any]] = {}
        skipped = []
        for (event_id,) in event_rows:
            event_snaps = collect_event(con, sport, str(event_id), max(1, int(sample_minutes)))
            if event_snaps:
                snapshots.extend(event_snaps)
            else:
                skipped.append({"event_id": str(event_id), "reason": "NO_PIT_VALID_IN_EVENT_SNAPSHOTS"})
            outcome = con.execute(
                "SELECT outcome,outcome_status,source,source_url,observed_at_utc FROM event_outcome WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if outcome and str(outcome[1]).upper() == "VERIFIED" and str(outcome[0]).upper() in {"A", "B"}:
                outcomes[str(event_id)] = {
                    "outcome": 1 if str(outcome[0]).upper() == "B" else 0,
                    "outcome_status": "VERIFIED",
                    "source": outcome[2],
                    "source_url": outcome[3],
                    "observed_at_utc": outcome[4],
                }
        snapshots.sort(key=lambda x: (x["event_time_utc"], x["event_id"], x["prediction_time_utc"], x["snapshot_id"]))
        return {
            "status": "READY" if snapshots else "BLOCKED",
            "sport": sport,
            "mode": mode,
            "sample_minutes": int(sample_minutes),
            "outcome_requirement_for_snapshot_collection": "NOT_REQUIRED",
            "oos_requires_verified_outcome": True,
            "events_scanned": len(event_rows),
            "events_with_snapshots": len({x["event_id"] for x in snapshots}),
            "snapshot_count": len(snapshots),
            "outcome_count": len(outcomes),
            "skipped_event_count": len(skipped),
            "skipped_events": skipped[:200],
            "snapshots": snapshots,
            "outcomes": outcomes,
            "pit_policy": "source snapshot must be EXACT and event-specific; source_available_at_utc <= prediction_time_utc; effective_at_utc <= observed_at_utc; prediction_time is inside event window",
            "promotion_status": "RESEARCH_ONLY_NO_AUTO_PROMOTION",
        }
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", required=True, choices=sorted(SPORT_STAT_POLICY))
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--output-dir", default="trajectory_delta")
    ap.add_argument("--sample-minutes", type=int, default=5)
    args = ap.parse_args()

    out_dir = ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    result = collect(args.sport, ROOT / args.db, sample_minutes=args.sample_minutes)

    snapshot_path = out_dir / f"trajectory_snapshots_{args.sport}.jsonl"
    outcome_path = out_dir / f"trajectory_outcomes_{args.sport}.json"
    report_path = out_dir / f"trajectory_collect_{args.sport}.json"

    with snapshot_path.open("w", encoding="utf-8") as fh:
        for row in result.get("snapshots", []):
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    outcome_path.write_text(json.dumps(result.get("outcomes", {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = dict(result)
    report.pop("snapshots", None)
    report.pop("outcomes", None)
    report["snapshot_path"] = str(snapshot_path.relative_to(ROOT))
    report["outcome_path"] = str(outcome_path.relative_to(ROOT))
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"READY", "BLOCKED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
