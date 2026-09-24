from __future__ import annotations

"""Research-only, strictly PIT-gated matchday intelligence.

The module converts canonical, timestamped observations already persisted in
sports_v45.sqlite into compact context for challenger routing. It never
directly changes production probabilities. A matchday observation is usable
only when both its observed/effective times and an EXACT source snapshot prove
availability by the prediction cutoff.
"""

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
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


def _exact_snapshot_exists(con, source, source_url, cutoff):
    return con.execute(
        """
        SELECT 1
          FROM source_snapshot ss
         WHERE ss.source=?
           AND COALESCE(ss.source_url,'')=COALESCE(?, '')
           AND ss.availability_status='EXACT'
           AND ss.source_available_at_utc IS NOT NULL
           AND datetime(ss.source_available_at_utc) <= datetime(?)
         LIMIT 1
        """,
        (source, source_url, cutoff),
    ).fetchone() is not None


def _latest_availability(con, event_id, cutoff):
    rows = con.execute(
        """
        SELECT participant_id,team_id,status,reason,source,source_url,
               observed_at_utc,effective_at_utc,confidence
          FROM availability a
         WHERE a.event_id=?
           AND datetime(a.observed_at_utc) <= datetime(?)
           AND a.effective_at_utc IS NOT NULL
           AND datetime(a.effective_at_utc) <= datetime(?)
         ORDER BY a.effective_at_utc DESC,a.observed_at_utc DESC
        """,
        (event_id, cutoff, cutoff),
    ).fetchall()
    latest = {}
    for row in rows:
        key = (row[0], row[1])
        if key in latest:
            continue
        if _exact_snapshot_exists(con, row[4], row[5], cutoff):
            latest[key] = row
    return list(latest.values()), rows


def _latest_lineup(con, event_id, cutoff):
    rows = con.execute(
        """
        SELECT ep.side,ep.participant_id,ep.team_id,ep.role,ep.lineup_status,
               ep.source,ep.source_url,ep.effective_at_utc,p.canonical_name
          FROM event_participant ep
          LEFT JOIN participant p ON p.participant_id=ep.participant_id
         WHERE ep.event_id=?
           AND ep.participant_id IS NOT NULL
           AND ep.effective_at_utc IS NOT NULL
           AND datetime(ep.effective_at_utc) <= datetime(?)
         ORDER BY ep.effective_at_utc DESC
        """,
        (event_id, cutoff),
    ).fetchall()
    latest = {}
    for row in rows:
        key = (row[0], row[1], row[2])
        if key in latest:
            continue
        if _exact_snapshot_exists(con, row[5], row[6], cutoff):
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

    teams = [
        r[0] for r in con.execute(
            "SELECT DISTINCT team_id FROM event_participant WHERE event_id=? AND team_id IS NOT NULL",
            (event_id,),
        ).fetchall()
    ]
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
             LIMIT 20
            """,
            (team_id, event_id, sport, cutoff),
        ).fetchall()
        times = [_dt(r[0]) for r in prior]
        times = [x for x in times if x is not None]
        last_dt = times[0] if times else None
        rest_days = ((edt - last_dt).total_seconds() / 86400.0) if last_dt else None
        out[team_id] = {
            "last_event_time_utc": last_dt.isoformat() if last_dt else None,
            "rest_days": rest_days,
            "games_last_3d": sum(1 for x in times if (edt - x).total_seconds() <= 3 * 86400),
            "games_last_7d": sum(1 for x in times if (edt - x).total_seconds() <= 7 * 86400),
            "games_last_14d": sum(1 for x in times if (edt - x).total_seconds() <= 14 * 86400),
        }
    return out


def _typed_context(con, event_id, cutoff):
    rows = con.execute(
        """
        SELECT stat_name,value_num,value_text,unit,observed_at_utc,
               effective_at_utc,source,source_url,confidence
          FROM match_stats ms
         WHERE ms.event_id=?
           AND datetime(ms.observed_at_utc) <= datetime(?)
           AND ms.effective_at_utc IS NOT NULL
           AND datetime(ms.effective_at_utc) <= datetime(?)
         ORDER BY stat_name,ms.effective_at_utc DESC,ms.observed_at_utc DESC
        """,
        (event_id, cutoff, cutoff),
    ).fetchall()

    buckets = {"weather": {}, "market": {}, "news": {}}
    for row in rows:
        name = str(row[0] or "").strip().lower()
        prefix = name.split(".", 1)[0] if "." in name else name.split("_", 1)[0]
        if prefix not in buckets or not _exact_snapshot_exists(con, row[6], row[7], cutoff):
            continue
        key = name
        if key in buckets[prefix]:
            continue
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


def _matchday_evidence_quality(con, event_id, cutoff, availability_rows, lineup_rows, typed):
    """Summarize evidence reliability for routing; never changes probabilities."""
    sources = set()
    confidences = []
    freshness = []
    conflict_keys = 0
    evidence_keys = 0

    def add_evidence(source, confidence, observed):
        if source:
            sources.add(str(source))
        try:
            c = float(confidence)
            if math.isfinite(c):
                confidences.append(min(max(c, 0.0), 1.0))
        except (TypeError, ValueError):
            pass
        age = _age_hours(observed, cutoff)
        if age is not None and math.isfinite(age):
            freshness.append(math.exp(-min(max(age, 0.0), 168.0) / 24.0))

    for row in availability_rows:
        add_evidence(row[4], row[8], row[6])

    for row in lineup_rows:
        add_evidence(row[5], None, row[7])

    for bucket in typed.values():
        for item in bucket.values():
            add_evidence(item.get("source"), item.get("confidence"), item.get("observed_at_utc"))

    raw = con.execute(
        """
        SELECT participant_id,team_id,status,source,source_url,observed_at_utc,effective_at_utc
          FROM availability
         WHERE event_id=?
           AND datetime(observed_at_utc) <= datetime(?)
           AND effective_at_utc IS NOT NULL
           AND datetime(effective_at_utc) <= datetime(?)
        """,
        (event_id, cutoff, cutoff),
    ).fetchall()
    states = {}
    for row in raw:
        if not _exact_snapshot_exists(con, row[3], row[4], cutoff):
            continue
        key = (row[0], row[1])
        states.setdefault(key, set()).add(_status_bucket(row[2]))
    for values in states.values():
        if len(values) > 1 and any(v not in {"UNKNOWN", "UNKNOWN_STATUS"} for v in values):
            conflict_keys += 1
        evidence_keys += 1

    typed_rows = con.execute(
        """
        SELECT stat_name,value_num,value_text,source,source_url
          FROM match_stats
         WHERE event_id=?
           AND datetime(observed_at_utc) <= datetime(?)
           AND effective_at_utc IS NOT NULL
           AND datetime(effective_at_utc) <= datetime(?)
        """,
        (event_id, cutoff, cutoff),
    ).fetchall()
    typed_values = {}
    for row in typed_rows:
        name = str(row[0] or "").strip().lower()
        prefix = name.split(".", 1)[0] if "." in name else name.split("_", 1)[0]
        if prefix not in {"weather", "market", "news"}:
            continue
        if not _exact_snapshot_exists(con, row[3], row[4], cutoff):
            continue
        value = row[1] if row[1] is not None else row[2]
        typed_values.setdefault(name, set()).add(str(value))
    for values in typed_values.values():
        evidence_keys += 1
        if len(values) > 1:
            conflict_keys += 1

    source_diversity = min(len(sources) / 4.0, 1.0) if sources else float("nan")
    conflict_rate = conflict_keys / evidence_keys if evidence_keys else float("nan")
    confidence_mean = sum(confidences) / len(confidences) if confidences else float("nan")
    freshness_score = sum(freshness) / len(freshness) if freshness else float("nan")
    return {
        "source_diversity": source_diversity,
        "conflict_rate": min(max(conflict_rate, 0.0), 1.0) if math.isfinite(conflict_rate) else float("nan"),
        "confidence_mean": confidence_mean,
        "freshness_score": freshness_score,
        "evidence_sources": sorted(sources),
        "conflict_keys": int(conflict_keys),
    }


def _build_with_connection(con, event_id, cutoff_utc):
    cutoff = _dt(cutoff_utc)
    if cutoff is None:
        raise ValueError("invalid cutoff_utc")

    event = con.execute(
        "SELECT event_id,sport,event_time_utc,status FROM event WHERE event_id=?",
        (event_id,),
    ).fetchone()
    if not event:
        raise KeyError(f"unknown event_id: {event_id}")
    event_time = _dt(event[2])
    if event_time is None:
        raise ValueError("event_time_utc is required")
    if cutoff > event_time:
        raise ValueError("prediction cutoff must not be after event_time_utc")

    availability, raw_availability = _latest_availability(con, event_id, cutoff_utc)
    lineup = _latest_lineup(con, event_id, cutoff_utc)
    schedule = _team_schedule_context(con, event_id, cutoff_utc)
    typed = _typed_context(con, event_id, cutoff_utc)
    quality = _matchday_evidence_quality(con, event_id, cutoff_utc, availability, lineup, typed)

    per_side = {}
    for side, participant_id, team_id, role, lineup_status, source, source_url, effective_at, name in lineup:
        state = per_side.setdefault(
            side,
            {
                "participant_count": 0,
                "lineup_known": 0,
                "lineup_confirmed": 0,
                "availability_out": 0,
                "availability_uncertain": 0,
                "availability_available": 0,
                "participants": [],
                "teams": set(),
            },
        )
        state["participant_count"] += 1
        if lineup_status:
            state["lineup_known"] += 1
            if str(lineup_status).strip().lower() in {
                "confirmed", "starter", "confirmed_starter"
            }:
                state["lineup_confirmed"] += 1
        if team_id:
            state["teams"].add(team_id)
        state["participants"].append(
            {
                "participant_id": participant_id,
                "name": name,
                "team_id": team_id,
                "role": role,
                "lineup_status": lineup_status,
                "source": source,
                "source_url": source_url,
                "effective_at_utc": effective_at,
            }
        )

    avail_by_key = {(r[0], r[1]): r for r in availability}
    for state in per_side.values():
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

    rest_by_side = {}
    for side, state in per_side.items():
        for team_id in state["teams"]:
            rest_by_side[team_id] = schedule.get(team_id, {})

    f = {
        "availability_out_side_a": per_side.get("A", {}).get("availability_out"),
        "availability_out_side_b": per_side.get("B", {}).get("availability_out"),
        "availability_uncertain_side_a": per_side.get("A", {}).get("availability_uncertain"),
        "availability_uncertain_side_b": per_side.get("B", {}).get("availability_uncertain"),
        "lineup_known_side_a": per_side.get("A", {}).get("lineup_known"),
        "lineup_known_side_b": per_side.get("B", {}).get("lineup_known"),
        "lineup_confirmed_side_a": per_side.get("A", {}).get("lineup_confirmed"),
        "lineup_confirmed_side_b": per_side.get("B", {}).get("lineup_confirmed"),
        "weather_signal_count": len(typed["weather"]),
        "market_signal_count": len(typed["market"]),
        "news_signal_count": len(typed["news"]),
        "matchday_source_diversity": quality["source_diversity"],
        "matchday_conflict_rate": quality["conflict_rate"],
        "matchday_confidence_mean": quality["confidence_mean"],
        "matchday_freshness_score": quality["freshness_score"],
    }

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
        "rest_schedule": rest_by_side,
        "typed_context": typed,
        "features": f,
        "evidence_counts": {
            "availability_latest": len(availability),
            "availability_raw_updates": len(raw_availability),
            "lineup_rows": len(lineup),
            "weather": len(typed["weather"]),
            "market": len(typed["market"]),
            "news": len(typed["news"]),
            "matchday_quality": quality,
        },
        "policy": (
            "research_only; cutoff_strict; observed_at_and_effective_at_must_not_exceed_cutoff; "
            "exact_source_snapshot_required; missing_signals_are_unknown_not_zero; "
            "no direct probability override"
        ),
    }
    payload["feature_snapshot_hash"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()
    return payload


def build_matchday_intelligence(event_id: str, cutoff_utc: str, db_path: Path = DB) -> dict:
    con = sqlite3.connect(db_path)
    try:
        return _build_with_connection(con, event_id, cutoff_utc)
    finally:
        con.close()


def build_matchday_context_rows(rows, db_path: Path = DB):
    """Return fixed-width PIT-safe router context for event rows."""
    con = sqlite3.connect(db_path)
    out = []
    try:
        for row in rows:
            event_id, event_time = str(row[0]), str(row[1])
            dt = _dt(event_time)
            if dt is None:
                out.append([float("nan")] * 10)
                continue
            cutoff = (dt - timedelta(minutes=60)).isoformat()
            try:
                payload = _build_with_connection(con, event_id, cutoff)
                out.append(router_context_vector(payload))
            except Exception:
                out.append([float("nan")] * 10)
    finally:
        con.close()
    return out


def router_context_vector(payload: dict) -> list[float]:
    """Convert matchday state to bounded context; unknown evidence remains NaN."""
    f = payload.get("features") or {}
    a = payload.get("lineup", {}).get("A", {})
    b = payload.get("lineup", {}).get("B", {})
    rest = payload.get("rest_schedule", {})

    def diff(name):
        x, y = f.get(name + "_side_a"), f.get(name + "_side_b")
        return float(x - y) if x is not None and y is not None else float("nan")

    def team_rest(state):
        vals = [
            rest[t].get("rest_days")
            for t in (state.get("teams") or [])
            if isinstance(rest.get(t), dict) and rest[t].get("rest_days") is not None
        ]
        return float(vals[0]) if vals else float("nan")

    rest_diff = team_rest(a) - team_rest(b)
    if not (rest_diff == rest_diff):
        rest_diff = float("nan")

    counts = [
        f.get("weather_signal_count"),
        f.get("market_signal_count"),
        f.get("news_signal_count"),
    ]
    observed_counts = [float(x) for x in counts if x is not None]
    evidence_density = (
        min(sum(observed_counts) / 12.0, 1.0) if observed_counts else float("nan")
    )

    confirmed_any = 1.0 if (
        (f.get("lineup_confirmed_side_a") or 0) > 0
        or (f.get("lineup_confirmed_side_b") or 0) > 0
    ) else 0.0

    return [
        diff("availability_out"),
        diff("availability_uncertain"),
        diff("lineup_confirmed"),
        rest_diff,
        float(f["weather_signal_count"]) if f.get("weather_signal_count") is not None else float("nan"),
        float(f["market_signal_count"]) if f.get("market_signal_count") is not None else float("nan"),
        float(f["news_signal_count"]) if f.get("news_signal_count") is not None else float("nan"),
        evidence_density,
        diff("lineup_known"),
        confirmed_any,
        float(f["matchday_source_diversity"]) if f.get("matchday_source_diversity") is not None else float("nan"),
        float(f["matchday_conflict_rate"]) if f.get("matchday_conflict_rate") is not None else float("nan"),
        float(f["matchday_confidence_mean"]) if f.get("matchday_confidence_mean") is not None else float("nan"),
        float(f["matchday_freshness_score"]) if f.get("matchday_freshness_score") is not None else float("nan"),
    ]


__all__ = [
    "build_matchday_intelligence",
    "build_matchday_context_rows",
    "router_context_vector",
]
