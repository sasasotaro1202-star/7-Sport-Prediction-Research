from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
SPORTS = ("valorant", "basketball", "volleyball", "tennis", "ufc", "rizin", "f1", "rugby", "boxing")
ACTIVE_SPORTS = ("valorant", "basketball", "volleyball", "ufc", "rizin")
DEFERRED_SPORTS = ("tennis", "f1", "rugby", "boxing")
MAX_SNAPSHOT_AGE_HOURS = 72


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now().isoformat()


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--sport", choices=SPORTS)
    args = ap.parse_args()

    checks: list[dict] = []
    fatal: list[str] = []
    pending: list[str] = []

    if not DB.exists() or DB.stat().st_size == 0:
        fatal.append("database_missing_or_empty")
    else:
        con = None
        try:
            con = sqlite3.connect(f"file:{DB.resolve()}?mode=ro", uri=True)
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            checks.append({"check": "sqlite_integrity", "ok": integrity == "ok", "result": integrity})
            if integrity != "ok":
                fatal.append("database_integrity_failure")

            tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            required = {
                "event", "participant", "event_participant", "match_stats",
                "source_snapshot", "event_outcome", "pit_replay",
                "pit_feature_snapshot", "model_state_snapshot", "collection_state",
            }
            missing = sorted(required - tables)
            checks.append({"check": "required_tables", "ok": not missing, "missing": missing})
            if missing:
                fatal.append("required_tables_missing")

            scope = (args.sport,) if args.sport else SPORTS
            counts = {k: int(v) for k, v in con.execute("select sport,count(*) from event group by sport")}
            miss = [s for s in scope if counts.get(s, 0) == 0 and s not in DEFERRED_SPORTS]
            checks.append({
                "check": "sports_present",
                "ok": not miss,
                "counts": {s: counts.get(s, 0) for s in scope},
                "missing": miss,
                "deferred": [s for s in scope if s in DEFERRED_SPORTS],
            })
            if miss:
                pending.append("sport_coverage_incomplete")
            if any(s in DEFERRED_SPORTS for s in scope):
                checks.append({"check": "explicit_deferred_sports", "ok": True, "sports": [s for s in scope if s in DEFERRED_SPORTS]})

            bad = con.execute(
                "select count(*) from event where event_time_utc is not null "
                "and datetime(event_time_utc) < '1950-01-01'"
            ).fetchone()[0]
            checks.append({"check": "event_time_sanity", "ok": bad == 0, "bad_rows": int(bad)})
            if bad:
                fatal.append("invalid_event_time")

            exact_missing = con.execute(
                "select count(*) from source_snapshot "
                "where availability_status='EXACT' and source_available_at_utc is null"
            ).fetchone()[0]
            unver = con.execute(
                "select count(*) from source_snapshot where availability_status='UNVERIFIABLE'"
            ).fetchone()[0]
            checks.append({
                "check": "source_timing_transparency",
                "ok": exact_missing == 0,
                "exact_missing_source_available_at": int(exact_missing),
                "unverifiable_source_timestamps": int(unver),
                "policy": "UNVERIFIABLE is excluded from strict PIT learning",
            })
            if exact_missing:
                fatal.append("exact_source_missing_availability_time")

            latest_rows = con.execute(
                "select sport,max(retrieved_at_utc) from source_snapshot "
                "where sport is not null group by sport"
            ).fetchall()
            latest = {sport: parse_utc(ts) for sport, ts in latest_rows}
            age_hours = {
                sport: None if latest.get(sport) is None else round((now() - latest[sport]).total_seconds() / 3600, 2)
                for sport in scope
            }
            stale = [sport for sport in scope if age_hours[sport] is None or age_hours[sport] > MAX_SNAPSHOT_AGE_HOURS]
            checks.append({
                "check": "source_snapshot_freshness",
                "ok": not stale,
                "max_age_hours": MAX_SNAPSHOT_AGE_HOURS,
                "age_hours": age_hours,
                "stale_or_missing": stale,
                "policy": "stale data may support degraded research but must not silently count as fresh production coverage",
            })
            if stale:
                pending.append("stale_or_missing_source_snapshot")

            if "f1" in scope:
                badf = con.execute(
                    "select count(*) from event_participant ep join event e on e.event_id=ep.event_id "
                    "where e.sport='f1' and lower(coalesce(ep.role,'')) <> 'driver'"
                ).fetchone()[0]
                checks.append({"check": "f1_event_participant_integrity", "ok": badf == 0, "bad_rows": int(badf)})
                if badf:
                    fatal.append("f1_non_driver_event_participants")

            ctx = {k: int(v) for k, v in con.execute(
                "select e.sport,count(*) from match_stats ms join event e on e.event_id=ms.event_id "
                "where ms.stat_name='ctx_international_flag' and ms.value_num=1 and ms.quality_status='EXACT' "
                "group by e.sport"
            )}
            cm = [s for s in scope if ctx.get(s, 0) == 0]
            checks.append({
                "check": "international_context",
                "ok": not cm,
                "exact_international_context_rows": {s: ctx.get(s, 0) for s in scope},
                "missing": cm,
                "policy": "context is learned only when source availability is proven by the 60-minute cutoff",
            })
            if cm:
                pending.append("international_context_coverage_incomplete")

            leak = con.execute(
                "select count(*) from pit_replay where leakage_status not in ('PASS','UNKNOWN','CLEAN')"
            ).fetchone()[0]
            exact = con.execute(
                "select count(*) from pit_replay where replay_status='EXACT' and leakage_status in ('PASS','CLEAN')"
            ).fetchone()[0]
            checks.append({"check": "pit_leakage", "ok": leak == 0, "nonpass": int(leak), "exact_pass": int(exact)})
            if leak:
                fatal.append("pit_leakage_detected")
            if exact == 0:
                pending.append("no_exact_pit_replay_rows")

            outc = {k: int(v) for k, v in con.execute(
                "select sport,count(*) from event_outcome where outcome_status='VERIFIED' group by sport"
            )}
            om = [s for s in scope if outc.get(s, 0) == 0]
            checks.append({"check": "verified_outcomes", "ok": not om, "counts": {s: outc.get(s, 0) for s in scope}, "missing": om})
            if om:
                pending.append("verified_outcome_coverage_incomplete")

            mr = {k: int(v) for k, v in con.execute(
                "select sport,count(*) from model_state_snapshot where quality_status like 'ACCEPTED%' group by sport"
            )}
            mm = [s for s in scope if mr.get(s, 0) == 0]
            checks.append({"check": "accepted_models", "ok": not mm, "counts": {s: mr.get(s, 0) for s in scope}, "missing": mm})
            if mm:
                pending.append("accepted_model_coverage_incomplete")

            states = con.execute("select sport,scope,completed from collection_state").fetchall()
            checks.append({"check": "checkpoint_state", "ok": True, "states": len(states), "completed": sum(int(x[2]) for x in states)})
        except sqlite3.DatabaseError as exc:
            fatal.append(f"database_read_failure:{type(exc).__name__}")
        finally:
            if con is not None:
                con.close()

    strict_pending = bool(pending) and args.strict
    status = "FAIL" if fatal or strict_pending else ("PASS_WITH_PENDING" if pending else "PASS")
    report = {
        "timestamp_utc": iso_now(),
        "status": status,
        "fatal": fatal,
        "pending": sorted(set(pending)),
        "checks": checks,
        "strict": args.strict,
        "scope": args.sport or "global",
        "policy": {
            "fatal_integrity_errors_block_publish": True,
            "coverage_pending_does_not_block_hourly_pipeline": not args.strict,
            "strict_mode_requires_full_coverage_and_models": True,
            "stale_source_snapshots_do_not_count_as_fresh_production_coverage": True,
        },
    }
    out = ROOT / "results/quality_gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(2 if fatal or strict_pending else 0)


if __name__ == "__main__":
    main()
