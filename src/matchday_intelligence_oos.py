from __future__ import annotations

"""Research-only, PIT-safe matchday intelligence feature builder.

This layer does not invent missing signals and does not change production
probabilities. It converts prediction-time observations already persisted in
the canonical database into a compact, auditable state object that can later
be consumed by sport-specific challenger experts.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"


def _dt(value):
    if not value:
        return None
    try:
        x = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _age_hours(observed, cutoff):
    a, c = _dt(observed), _dt(cutoff)
    if a is None or c is None:
        return None
    return max(0.0, (c - a).total_seconds() / 3600.0)


def _status_bucket(status):
    s = str(status or "").strip().lower()
    if s in {"out", "withdrawn", "inactive", "ruled_out", "suspended"}:
        return "OUT"
    if s in {"limited", "minutes_limit", "questionable", "doubtful"}:
        return "LIMITED_OR_UNCERTAIN"
    if s in {"active", "available", "probable", "confirmed_active", "starter"}:
        return "AVAILABLE"
    if s:
        return "UNKNOWN_STATUS"
    return "UNKNOWN"


def _latest_rows(con, table, where_sql, params):
    query = f"""
        SELECT * FROM (
            SELECT t.*,
                   ROW_NUMBER() OVER (
                     PARTITION BY {where_sql}
                     ORDER BY COALESCE(t.effective_at_utc,t.observed_at_utc) DESC,
                              t.observed_at_utc DESC
                   ) AS rn
            FROM {table} t
        ) q
        WHERE q.rn=1
    """
    return con.execute(query, params).fetchall()


def _signal_rows(con, event_id, cutoff):
    cutoff_dt = _dt(cutoff)
    if cutoff_dt is None:
        return [], []

    availability = con.execute(
        """
        SELECT participant_id,team_id,status,reason,source,source_url,
               observed_at_utc,effective_at_utc,confidence
        FROM availability
        WHERE event_id=?
          AND datetime(observed_at_utc) <= datetime(?)
          AND effective_at_utc IS NOT NULL
          AND datetime(effective_at_utc) <= datetime(?)
        ORDER BY COALESCE(effective_at_utc,observed_at_utc) DESC,
                 observed_at_utc DESC
        """,
        (event_id, cutoff, cutoff),
    ).fetchall()

    # Multiple updates about the same participant/team are reduced to the
    # latest observation available at the prediction cutoff.
    latest = {}
    for row in availability:
        key = (row[0], row[1])
        if key not in latest:
            latest[key] = row

    return list(latest.values()), availability


def _participant_and_lineup(con, event_id, cutoff):
    rows = con.execute(
        """
        SELECT ep.side,ep.participant_id,ep.team_id,ep.role,ep.lineup_status,
               ep.source,ep.source_url,ep.effective_at_utc,
               p.canonical_name
        FROM event_participant ep
        LEFT JOIN participant p ON p.participant_id=ep.participant_id
        WHERE ep.event_id=?
          AND ep.participant_id IS NOT NULL
          AND ep.effective_at_utc IS NOT NULL
          AND datetime(ep.effective_at_utc) <= datetime(?)
        """,
        (event_id, cutoff),
    ).fetchall()
    latest = {}
    for row in rows:
        key = (row[0], row[1], row[2])
        effective = _dt(row[7])
        prev = latest.get(key)
        if prev is None or (_dt(prev[7]) or datetime.min.replace(tzinfo=timezone.utc)) < (effective or datetime.min.replace(tzinfo=timezone.utc)):
            latest[key] = row
    return list(latest.values())


def _team_schedule_context(con, event_id, cutoff):
    event = con.execute(
        "SELECT sport,event_time_utc FROM event WHERE event_id=?",
        (event_id,),
    ).fetchone()
    if not event:
        return {}
    sport, current_time = event
    cdt = _dt(cutoff)
    edt = _dt(current_time)
    if cdt is None or edt is None:
        return {}

    teams = [r[0] for r in con.execute(
        "SELECT DISTINCT team_id FROM event_participant WHERE event_id=? AND team_id IS NOT NULL",
        (event_id,),
    ).fetchall()]

    out = {}
    for team_id in teams:
        prior = con.execute(
            """
            SELECT e.event_time_utc
            FROM event_participant ep
            JOIN event e ON e.event_id=ep.event_id
            WHERE ep.team_id=?
              AND ep.event_id<>?
              AND e.sport=?
              AND e.event_time_utc IS NOT NULL
              AND datetime(e.event_time_utc) < datetime(?)
              AND UPPER(COALESCE(e.status,'')) NOT IN ('CANCELLED','VOID')
            ORDER BY e.event_time_utc DESC
            LIMIT 14
            """,
            (team_id, event_id, sport, cutoff),
        ).fetchall()

        times = [_dt(r[0]) for r in prior]
        times = [x for x in times if x is not None]
        last_dt = times[0] if times else None
        rest_days = ((edt - last_dt).total_seconds() / 86400.0) if last_dt else None
        games_3d = sum(1 for x in times if (edt - x).total_seconds() <= 3 * 86400)
        games_7d = sum(1 for x in times if (edt - x).total_seconds() <= 7 * 86400)
        games_14d = sum(1 for x in times if (edt - x).total_seconds() <= 14 * 86400)

        out[team_id] = {
            "last_event_time_utc": last_dt.isoformat() if last_dt else None,
            "rest_days": rest_days,
            "games_last_3d": games_3d,
            "games_last_7d": games_7d,
            "games_last_14d": games_14d,
        }
    return out


def _typed_match_stats(con, event_id, cutoff):
    rows = con.execute(
        """
        SELECT stat_name,value_num,value_text,unit,observed_at_utc,
               effective_at_utc,source,source_url,confidence
        FROM match_stats
        WHERE event_id=?
          AND datetime(observed_at_utc) <= datetime(?)
          AND effective_at_utc IS NOT NULL
          AND datetime(effective_at_utc) <= datetime(?)
        ORDER BY stat_name,
                 COALESCE(effective_at_utc,observed_at_utc) DESC,
                 observed_at_utc DESC
        """,
        (event_id, cutoff, cutoff),
    ).fetchall()

    # Only explicit namespaces are treated as matchday signals. Historical
    # performance statistics remain separate and are not reclassified here.
    buckets = {"weather": {}, "market": {}, "news": {}}
    for row in rows:
        name = str(row[0] or "").strip().lower()
        prefix = name.split(".", 1)[0] if "." in name else name.split("_", 1)[0]
        if prefix not in buckets:
            continue
        key = name
        if key not in buckets[prefix]:
            buckets[prefix][key] = {
                "value_num": row[1],
                "value_text": row[2],
                "unit": row[3],
                "observed_at_utc": row[4],
                "effective_at_utc": row[5],
                "source": row[6],
                "source_url": row[7],
                "confidence": row[8],
                "age_hours_at_cutoff": _age_hours(row[4], cutoff),
            }
    return buckets


def build_matchday_intelligence(event_id: str, cutoff_utc: str, db_path: Path = DB) -> dict:
    cutoff = _dt(cutoff_utc)
    if cutoff is None:
        raise ValueError("invalid cutoff_utc")

    con = sqlite3.connect(db_path)
    try:
        event = con.execute(
            "SELECT event_id,sport,event_time_utc,status FROM event WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if not event:
            raise KeyError(f"unknown event_id: {event_id}")
        event_time = _dt(event[2])
        if event_time is None:
            raise ValueError("event_time_utc is required for matchday intelligence")
        if cutoff > event_time:
            raise ValueError("prediction cutoff must not be after event_time_utc")

        availability, raw_availability = _signal_rows(con, event_id, cutoff_utc)
        lineup = _participant_and_lineup(con, event_id, cutoff_utc)
        schedule = _team_schedule_context(con, event_id, cutoff_utc)
        typed = _typed_match_stats(con, event_id, cutoff_utc)

        per_side = {}
        for side, participant_id, team_id, role, lineup_status, source, source_url, effective_at, name in lineup:
            side_state = per_side.setdefault(side, {
                "participant_count": 0,
                "lineup_known": 0,
                "lineup_confirmed": 0,
                "availability_out": 0,
                "availability_uncertain": 0,
                "availability_available": 0,
                "participants": [],
                "teams": set(),
            })
            side_state["participant_count"] += 1
            if lineup_status:
                side_state["lineup_known"] += 1
                if str(lineup_status).strip().lower() in {"confirmed", "starter", "confirmed_starter"}:
                    side_state["lineup_confirmed"] += 1
            if team_id:
                side_state["teams"].add(team_id)
            side_state["participants"].append({
                "participant_id": participant_id,
                "name": name,
                "team_id": team_id,
                "role": role,
                "lineup_status": lineup_status,
                "source": source,
                "source_url": source_url,
                "effective_at_utc": effective_at,
            })

        avail_by_key = {(r[0], r[1]): r for r in availability}
        for side in per_side:
            state = per_side[side]
            for p in state["participants"]:
                row = avail_by_key.get((p["participant_id"], p["team_id"]))
                if row:
                    bucket = _status_bucket(row[2])
                    p["availability_status"] = bucket
                    p["availability_reason"] = row[3]
                    p["availability_source"] = row[4]
                    p["availability_observed_at_utc"] = row[6]
                    p["availability_confidence"] = row[8]
                    if bucket == "OUT":
                        state["availability_out"] += 1
                    elif bucket == "LIMITED_OR_UNCERTAIN":
                        state["availability_uncertain"] += 1
                    elif bucket == "AVAILABLE":
                        state["availability_available"] += 1
                else:
                    p["availability_status"] = "UNKNOWN"

            state["teams"] = sorted(state["teams"])

        # Convert sets before serialisation.
        for state in per_side.values():
            state["teams"] = sorted(state["teams"])

        features = {
            "availability_out_side_a": int(per_side.get("A", {}).get("availability_out", 0)),
            "availability_out_side_b": int(per_side.get("B", {}).get("availability_out", 0)),
            "availability_uncertain_side_a": int(per_side.get("A", {}).get("availability_uncertain", 0)),
            "availability_uncertain_side_b": int(per_side.get("B", {}).get("availability_uncertain", 0)),
            "lineup_known_side_a": int(per_side.get("A", {}).get("lineup_known", 0)),
            "lineup_known_side_b": int(per_side.get("B", {}).get("lineup_known", 0)),
            "lineup_confirmed_side_a": int(per_side.get("A", {}).get("lineup_confirmed", 0)),
            "lineup_confirmed_side_b": int(per_side.get("B", {}).get("lineup_confirmed", 0)),
            "weather_signal_count": len(typed["weather"]),
            "market_signal_count": len(typed["market"]),
            "news_signal_count": len(typed["news"]),
        }

        team_rest = {}
        for side, state in per_side.items():
            for team_id in state["teams"]:
                team_rest[team_id] = schedule.get(team_id, {})

        payload = {
            "event_id": event[0],
            "sport": event[1],
            "event_time_utc": event[2],
            "prediction_cutoff_at_utc": cutoff.isoformat(),
            "availability": [
                {
                    "participant_id": r[0],
                    "team_id": r[1],
                    "status": _status_bucket(r[2]),
                    "raw_status": r[2],
                    "reason": r[3],
                    "source": r[4],
                    "source_url": r[5],
                    "observed_at_utc": r[6],
                    "effective_at_utc": r[7],
                    "confidence": r[8],
                    "age_hours_at_cutoff": _age_hours(r[6], cutoff_utc),
                }
                for r in availability
            ],
            "lineup": per_side,
            "rest_schedule": team_rest,
            "typed_context": typed,
            "features": features,
            "evidence_counts": {
                "availability_latest": len(availability),
                "availability_raw_updates": len(raw_availability),
                "lineup_rows": len(lineup),
                "weather": len(typed["weather"]),
                "market": len(typed["market"]),
                "news": len(typed["news"]),
            },
            "policy": (
                "research_only; cutoff_strict; observed_at_and_effective_at_must_not_exceed_cutoff; "
                "missing_signals_are_unknown_not_zero; no direct probability override"
            ),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
        payload["feature_snapshot_hash"] = hashlib.sha256(encoded).hexdigest()
        return payload
    finally:
        con.close()


__all__ = ["build_matchday_intelligence"]
