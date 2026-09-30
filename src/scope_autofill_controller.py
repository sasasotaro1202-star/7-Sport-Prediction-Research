from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.research_cycle_v4 import target_event
from src.competition_profiles import resolve_profile

ROOT = Path(__file__).resolve().parents[1]
SHARED_DB = ROOT / "data/db/sports_v45.sqlite"
DEDICATED_DBS = {
    "rugby": ROOT / "data/db/rugby_v45.sqlite",
    "boxing": ROOT / "data/db/boxing_v45.sqlite",
}
OUT_DIR = ROOT / "results"
MIN_EVENTS = 120
MIN_VERIFIED = 80
MIN_EXACT_PIT_RATIO = 0.95
DEFAULT_MAX_ACTIONS = 3

# Free, repository-native collection routes. No commercial API is invoked.
ACTIONS = {
    "basketball": [
        ("historical_b_league", [sys.executable, "-m", "src.basketball_cdn_backfill", "--historical"], 900),
        ("incremental_official", [sys.executable, "-m", "src.seven_sport_production", "--sport", "basketball", "--days-back", "30", "--days-forward", "14"], 420),
    ],
    "volleyball": [
        ("historical_fivb", [sys.executable, "-m", "src.robust_sport_adapters_v4", "--sport", "volleyball", "--max-pages", "120"], 720),
        ("incremental_sources", [sys.executable, "-m", "src.seven_sport_production", "--sport", "volleyball", "--days-back", "30", "--days-forward", "14"], 420),
    ],
    "ufc": [
        ("ufc_historical_api", [sys.executable, "-m", "src.ufc_api_backfill", "--limit", "500"], 480),
        ("ufc_fight_history", [sys.executable, "-m", "src.robust_sport_adapters_v4", "--sport", "ufc"], 720),
    ],
    "rizin": [
        ("rizin_historical", [sys.executable, "-m", "src.robust_sport_adapters_v4", "--sport", "rizin", "--max-pages", "120"], 720),
        ("rizin_incremental", [sys.executable, "-m", "src.seven_sport_production", "--sport", "rizin", "--days-back", "30", "--days-forward", "14"], 420),
    ],
    "valorant": [
        ("valorant_history", [sys.executable, "-m", "src.robust_sport_adapters_v4", "--sport", "valorant", "--vlr-pages", "60"], 720),
        ("valorant_incremental", [sys.executable, "-m", "src.seven_sport_production", "--sport", "valorant", "--days-back", "30", "--days-forward", "14"], 420),
    ],
    "tennis": [
        ("tennis_archive_history", [sys.executable, "-m", "src.tennis_public_backfill"], 1200),
    ],
    "f1": [
        ("f1_openf1_history", [sys.executable, "-m", "src.f1_openf1_backfill"], 1200),
    ],
    "rugby": [
        ("rugby_official_history", [sys.executable, "-m", "src.rugby_production", "--max-pages", "180"], 900),
    ],
    "boxing": [
        ("boxing_public_history", [sys.executable, "-m", "src.boxing_production", "--ingest-history"], 900),
    ],
}

SUPPORTED_ACTIVE_PIT = {"basketball", "volleyball", "ufc", "rizin", "valorant"}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path(sport: str) -> Path:
    return DEDICATED_DBS.get(sport, SHARED_DB)


def _is_target(sport: str, name: object, competition_id: object) -> bool:
    if sport in SUPPORTED_ACTIVE_PIT or sport in {"basketball", "volleyball"}:
        return bool(target_event(sport, str(name or ""), str(competition_id or "")))
    return True


def metrics(sport: str) -> dict:
    path = db_path(sport)
    if not path.is_file():
        return {
            "db": str(path.relative_to(ROOT)),
            "events": 0,
            "verified_outcomes": 0,
            "exact_pit_events": 0,
            "exact_pit_ratio": 0.0,
        }
    con = sqlite3.connect(path)
    try:
        rows = con.execute(
            """SELECT event_id,event_time_utc,name,competition_id
                 FROM event
                WHERE sport=?
             ORDER BY event_time_utc,event_id""",
            (sport,),
        ).fetchall()
        selected = [r for r in rows if _is_target(sport, r[2], r[3])]
        selected_ids = [str(r[0]) for r in selected]
        if selected_ids:
            marks = ",".join("?" * len(selected_ids))
            verified = int(con.execute(
                f"""SELECT COUNT(*)
                       FROM event_outcome
                      WHERE sport=? AND outcome_status='VERIFIED'
                        AND event_id IN ({marks})""",
                (sport, *selected_ids),
            ).fetchone()[0])
        else:
            verified = 0

        exact = 0
        for event_id, event_time, _name, _competition in selected:
            if not event_time:
                continue
            try:
                et = datetime.fromisoformat(str(event_time).replace("Z", "+00:00"))
                if et.tzinfo is None:
                    et = et.replace(tzinfo=timezone.utc)
                cutoff = et - timedelta(minutes=60)
            except Exception:
                continue
            ok = con.execute(
                """SELECT 1
                     FROM source_snapshot
                    WHERE sport=?
                      AND availability_status='EXACT'
                      AND source_available_at_utc IS NOT NULL
                      AND source_available_at_utc<=?
                      AND (event_time_utc IS NULL OR event_time_utc=?)
                    LIMIT 1""",
                (sport, cutoff.isoformat(), str(event_time)),
            ).fetchone()
            if ok:
                exact += 1
        return {
            "db": str(path.relative_to(ROOT)),
            "events": len(selected),
            "verified_outcomes": verified,
            "exact_pit_events": exact,
            "exact_pit_ratio": exact / max(len(selected), 1),
            "target_filter": sport in {"basketball", "volleyball"},
        }
    finally:
        con.close()


def select_action(sport: str, current: dict, attempted: set[str]) -> tuple[str, list[str], int] | None:
    if current["events"] < MIN_EVENTS:
        priority = ACTIONS[sport]
    elif current["verified_outcomes"] < MIN_VERIFIED:
        priority = ACTIONS[sport]
    elif current["exact_pit_ratio"] < MIN_EXACT_PIT_RATIO and sport in SUPPORTED_ACTIVE_PIT:
        # Force a provenance-sensitive replay before considering any selection.
        return (
            "strict_pit_replay",
            [sys.executable, "-m", "src.pit_replay_builder", "--force", "--sport", sport],
            1500,
        )
    else:
        priority = ACTIONS[sport]
    for name, command, timeout in priority:
        if name not in attempted:
            return name, command, timeout
    if current["exact_pit_ratio"] < MIN_EXACT_PIT_RATIO and sport in SUPPORTED_ACTIVE_PIT and "strict_pit_replay" not in attempted:
        return (
            "strict_pit_replay",
            [sys.executable, "-m", "src.pit_replay_builder", "--force", "--sport", sport],
            1500,
        )
    return None


def run_action(name: str, command: list[str], timeout: int) -> dict:
    started = utc()
    try:
        p = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
        return {
            "action": name,
            "returncode": int(p.returncode),
            "status": "PASS" if p.returncode == 0 else "FAILED",
            "started_at_utc": started,
            "ended_at_utc": utc(),
            "stdout_tail": p.stdout[-6000:],
            "stderr_tail": p.stderr[-6000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "action": name,
            "returncode": 124,
            "status": "TIMEOUT",
            "started_at_utc": started,
            "ended_at_utc": utc(),
            "stdout_tail": str(exc.stdout or "")[-6000:],
            "stderr_tail": str(exc.stderr or "")[-6000:],
        }
    except Exception as exc:
        return {
            "action": name,
            "returncode": 125,
            "status": "FAILED",
            "started_at_utc": started,
            "ended_at_utc": utc(),
            "error": repr(exc),
        }



def competition_frontier(sport: str, limit: int = 25) -> list[dict]:
    path = db_path(sport)
    if not path.is_file():
        return []
    con = sqlite3.connect(path)
    try:
        rows = con.execute(
            """SELECT competition_id, COUNT(*) AS events,
                      SUM(CASE WHEN EXISTS (
                          SELECT 1 FROM event_outcome eo
                           WHERE eo.event_id=event.event_id
                             AND eo.outcome_status='VERIFIED'
                      ) THEN 1 ELSE 0 END) AS verified
                 FROM event
                WHERE sport=?
                  AND competition_id IS NOT NULL
                  AND TRIM(competition_id)<>''
             GROUP BY competition_id
             ORDER BY events DESC, competition_id
             LIMIT ?""",
            (sport, int(limit)),
        ).fetchall()
        out = []
        for competition_id, events, verified in rows:
            profile = resolve_profile(sport, competition_id, None)
            out.append({
                "competition_id": str(competition_id),
                "events": int(events or 0),
                "verified_outcomes": int(verified or 0),
                "profile_id": profile.get("profile_id"),
                "profile_matched": bool(profile.get("matched")),
                "dynamic_profile": bool(profile.get("dynamic", False)),
                "research_ready": bool(
                    int(events or 0) >= MIN_EVENTS
                    and int(verified or 0) >= MIN_VERIFIED
                ),
            })
        return out
    finally:
        con.close()

def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", required=True, choices=sorted(ACTIONS))
    ap.add_argument("--max-actions", type=int, default=DEFAULT_MAX_ACTIONS)
    ap.add_argument("--skip-discovery", action="store_true")
    args = ap.parse_args()

    sport = args.sport
    trace = []
    attempted: set[str] = set()
    before = metrics(sport)

    # Discovery is repeated every cycle before data selection so source candidates
    # can change independently of the current model/data state.
    if not args.skip_discovery:
        discovery = run_action(
            "continuous_source_discovery",
            [sys.executable, "-m", "src.scope_source_discovery"],
            600,
        )
        trace.append({"decision": "DISCOVER_SOURCES", **discovery})

    for _ in range(max(1, args.max_actions)):
        current = metrics(sport)
        if (
            current["events"] >= MIN_EVENTS
            and current["verified_outcomes"] >= MIN_VERIFIED
            and (
                current["exact_pit_ratio"] >= MIN_EXACT_PIT_RATIO
                or sport not in SUPPORTED_ACTIVE_PIT
            )
        ):
            trace.append({
                "decision": "DATA_THRESHOLD_REACHED",
                "metrics": current,
                "next": "MODEL_SELECTION",
            })
            break

        selected = select_action(sport, current, attempted)
        if selected is None:
            trace.append({
                "decision": "NO_UNTRIED_COLLECTION_ROUTE",
                "metrics": current,
                "next": "HOLD_AND_REDISCOVER_NEXT_CYCLE",
            })
            break

        name, command, timeout = selected
        attempted.add(name)
        trace.append({
            "decision": "SELECT_NEXT_ACTION",
            "reason": {
                "events_deficit": max(0, MIN_EVENTS - current["events"]),
                "verified_outcomes_deficit": max(0, MIN_VERIFIED - current["verified_outcomes"]),
                "exact_pit_ratio_deficit": max(0.0, MIN_EXACT_PIT_RATIO - current["exact_pit_ratio"]),
            },
            "selected_action": name,
            "command": command[2:] if len(command) >= 3 else command,
            **run_action(name, command, timeout),
        })

    after = metrics(sport)
    frontier = competition_frontier(sport)
    progress = {
        "event_delta": after["events"] - before["events"],
        "verified_outcome_delta": after["verified_outcomes"] - before["verified_outcomes"],
        "exact_pit_event_delta": after["exact_pit_events"] - before["exact_pit_events"],
        "exact_pit_ratio_delta": after["exact_pit_ratio"] - before["exact_pit_ratio"],
    }
    threshold_reached = (
        after["events"] >= MIN_EVENTS
        and after["verified_outcomes"] >= MIN_VERIFIED
        and (after["exact_pit_ratio"] >= MIN_EXACT_PIT_RATIO or sport not in SUPPORTED_ACTIVE_PIT)
    )
    selection_action = "RUN_COMPETITION_OOS" if threshold_reached and sport in SUPPORTED_ACTIVE_PIT else "KEEP_COLLECTING_OR_HOLD"
    failed_actions = [x for x in trace if x.get("returncode", 0) not in (0, None)]
    report = {
        "version": "scope-autofill-controller-v1",
        "sport": sport,
        "status": "THRESHOLD_REACHED" if threshold_reached else "DATA_STILL_NEEDED",
        "free_only": True,
        "before": before,
        "after": after,
        "progress": progress,
        "thresholds": {
            "events": MIN_EVENTS,
            "verified_outcomes": MIN_VERIFIED,
            "exact_pit_ratio": MIN_EXACT_PIT_RATIO,
        },
        "selection_continues": True,
        "search_continues": True,
        "auto_data_addition_continues": True,
        "failed_actions": len(failed_actions),
        "trace": trace,
        "next_cycle": "REPEAT_UNTIL_THRESHOLD_OR_NO_SAFE_ROUTE",
        "selection_action": selection_action,
    }
    out = OUT_DIR / f"scope_autofill_{sport}.json"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failed_actions else 2


if __name__ == "__main__":
    raise SystemExit(main())
