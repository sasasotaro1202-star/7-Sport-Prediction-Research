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
          AND EXISTS (
                SELECT 1 FROM source_snapshot ss
                 WHERE ss.source=match_stats.source
                   AND COALESCE(ss.source_url,'')=COALESCE(match_stats.source_url,'')
                   AND ss.availability_status='EXACT'
                   AND ss.source_available_at_utc IS NOT NULL
                   AND datetime(ss.source_available_at_utc) <= datetime(?)
          )
          AND EXISTS (
                SELECT 1 FROM source_snapshot ss
                 WHERE ss.source=availability.source
                   AND COALESCE(ss.source_url,'')=COALESCE(availability.source_url,'')
                   AND ss.availability_status='EXACT'
                   AND ss.source_available_at_utc IS NOT NULL
                   AND datetime(ss.source_available_at_utc) <= datetime(?)
          )
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
          AND EXISTS (
                SELECT 1 FROM source_snapshot ss
                 WHERE ss.source=ep.source
                   AND COALESCE(ss.source_url,'')=COALESCE(ep.source_url,'')
                   AND ss.availability_status='EXACT'
                   AND ss.source_available_at_utc IS NOT NULL
                   AND datetime(ss.source_available_at_utc) <= datetime(?)
          )
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


def router_context_vector(payload: dict) -> list[float]:
    """Compact PIT-safe context for the uncertainty router; unknowns remain NaN."""
    f = payload.get("features") or {}
    a = payload.get("lineup", {}).get("A", {})
    b = payload.get("lineup", {}).get("B", {})
    ra = payload.get("rest_schedule", {})
    teams_a = a.get("teams") or []
    teams_b = b.get("teams") or []
    rest_a = [ra[t].get("rest_days") for t in teams_a if isinstance(ra.get(t), dict) and ra[t].get("rest_days") is not None]
    rest_b = [ra[t].get("rest_days") for t in teams_b if isinstance(ra.get(t), dict) and ra[t].get("rest_days") is not None]
    rest_a_v = float(rest_a[0]) if rest_a else float("nan")
    rest_b_v = float(rest_b[0]) if rest_b else float("nan")
    exact = payload.get("evidence_counts", {})
    total_signals = (
        int(exact.get("availability_latest", 0))
        + int(exact.get("lineup_rows", 0))
        + int(exact.get("weather", 0))
        + int(exact.get("market", 0))
        + int(exact.get("news", 0))
    )
    # Schema is fixed: missing values remain NaN and are handled by the router's
    # own missingness representation. The final element is an explicit evidence
    # density signal, not a zero-filled assumption.
    return [
        float(f.get("availability_out_side_a", float("nan")) - f.get("availability_out_side_b", float("nan")))
        if all(x is not None for x in (f.get("availability_out_side_a"), f.get("availability_out_side_b"))) else float("nan"),
        float(f.get("availability_uncertain_side_a", float("nan")) - f.get("availability_uncertain_side_b", float("nan")))
        if all(x is not None for x in (f.get("availability_uncertain_side_a"), f.get("availability_uncertain_side_b"))) else float("nan"),
        float(f.get("lineup_confirmed_side_a", float("nan")) - f.get("lineup_confirmed_side_b", float("nan")))
        if all(x is not None for x in (f.get("lineup_confirmed_side_a"), f.get("lineup_confirmed_side_b"))) else float("nan"),
        rest_a_v - rest_b_v if rest_a_v == rest_a_v and rest_b_v == rest_b_v else float("nan"),
        float(f.get("weather_signal_count", float("nan"))),
        float(f.get("market_signal_count", float("nan"))),
        float(f.get("news_signal_count", float("nan"))),
        float(total_signals),
        float(a.get("lineup_known", 0) - b.get("lineup_known", 0)),
        float(f.get("lineup_confirmed_side_a", 0) > 0 or f.get("lineup_confirmed_side_b", 0) > 0),
    ]


def build_matchday_context_rows(rows, db_path: Path = DB):
    """Build one router-context vector per (event_id,event_time) row using one DB connection."""
    con = sqlite3.connect(db_path)
    out = []
    try:
        for row in rows:
            eid, event_time = str(row[0]), str(row[1])
            dt = _dt(event_time)
            if dt is None:
                out.append([float("nan")] * 10)
                continue
            cutoff = (dt - __import__("datetime").timedelta(minutes=60)).isoformat()
            payload = _build_with_connection(con, eid, cutoff)
            out.append(router_context_vector(payload))
    finally:
        con.close()
    return out


def build_matchday_intelligence(event_id: str, cutoff_utc: str, db_path: Path = DB) -> dict:
    con = sqlite3.connect(db_path)
    try:
        return _build_with_connection(con, event_id, cutoff_utc)
    finally:
        con.close()


__all__ = ["build_matchday_intelligence"]
