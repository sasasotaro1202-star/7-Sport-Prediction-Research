from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPORTS = (
    "valorant", "basketball", "volleyball", "tennis", "ufc",
    "rizin", "f1", "rugby", "boxing",
)
DB = ROOT / "data/db/sports_v45.sqlite"


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def shared_counts(con, sport: str) -> dict:
    q = lambda sql: int(con.execute(sql, (sport,)).fetchone()[0])
    return {
        "events": q("SELECT COUNT(*) FROM event WHERE sport=?"),
        "timed_events": q("SELECT COUNT(*) FROM event WHERE sport=? AND event_time_utc IS NOT NULL"),
        "verified_outcomes": q(
            "SELECT COUNT(*) FROM event_outcome WHERE sport=? AND outcome_status='VERIFIED'"
        ),
        "pit_replayable": int(con.execute(
            "SELECT COUNT(*) FROM pit_replay WHERE replay_status='REPLAYABLE' "
            "AND event_id IN (SELECT event_id FROM event WHERE sport=?)", (sport,)
        ).fetchone()[0]),
        "pit_exact_clean": int(con.execute(
            "SELECT COUNT(*) FROM pit_replay WHERE replay_status='EXACT' "
            "AND leakage_status IN ('PASS','CLEAN') "
            "AND event_id IN (SELECT event_id FROM event WHERE sport=?)", (sport,)
        ).fetchone()[0]),
        "accepted_models": int(con.execute(
            "SELECT COUNT(*) FROM model_state_snapshot WHERE sport=? AND quality_status LIKE 'ACCEPTED%'",
            (sport,)
        ).fetchone()[0]),
    }


def separate_report(sport: str) -> dict:
    candidates = (
        ROOT / "results/research" / f"{sport}.json",
        ROOT / "results/v45" / f"{sport}_coverage.json",
    )
    for p in candidates:
        if p.is_file():
            obj = read_json(p)
            if isinstance(obj, dict):
                return {"path": str(p.relative_to(ROOT)), **obj}
    return {}


def main() -> int:
    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sports": {},
        "policy": {
            "scope": list(SPORTS),
            "all_nine_must_be_reported": True,
            "deferred_is_explicit_not_success": True,
            "pit_unknown_is_not_promoted": True,
        },
    }

    con = None
    try:
        if DB.is_file() and DB.stat().st_size > 0:
            con = sqlite3.connect(f"file:{DB.resolve()}?mode=ro", uri=True)
            for sport in SPORTS:
                counts = shared_counts(con, sport)
                extra = separate_report(sport)
                report["sports"][sport] = {
                    "events": counts["events"],
                    "timed_events": counts["timed_events"],
                    "verified_outcomes": counts["verified_outcomes"],
                    "pit_replayable": counts["pit_replayable"],
                    "pit_exact_clean": counts["pit_exact_clean"],
                    "accepted_models": counts["accepted_models"],
                    "research_status": extra.get("status"),
                    "research_reason": extra.get("reason") or extra.get("deferred_reason"),
                    "coverage_report": extra.get("path"),
                }
        else:
            for sport in SPORTS:
                extra = separate_report(sport)
                report["sports"][sport] = {
                    "events": int(extra.get("events", extra.get("counts", {}).get("events", 0)) or 0),
                    "timed_events": int(extra.get("timed_events", extra.get("counts", {}).get("timed_events", 0)) or 0),
                    "verified_outcomes": int(extra.get("verified_outcomes", 0) or 0),
                    "pit_replayable": 0,
                    "pit_exact_clean": int(extra.get("exact_pit_source_snapshots", 0) or 0),
                    "accepted_models": 0,
                    "research_status": extra.get("status"),
                    "research_reason": extra.get("reason") or extra.get("deferred_reason"),
                    "coverage_report": extra.get("path"),
                }
    finally:
        if con is not None:
            con.close()

    missing = [s for s in SPORTS if s not in report["sports"]]
    report["status"] = "OK" if not missing and len(report["sports"]) == 9 else "INCOMPLETE"
    report["missing_sports"] = missing

    out = ROOT / "results/nine_sport_lane_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
