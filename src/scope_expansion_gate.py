from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.competition_profiles import resolve_profile

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "SCOPE_EXPANSION_POLICY.json"
SCOPE_PATH = ROOT / "config" / "ACTIVE_SCOPE_9_SPORTS.json"
PROJECT_SCOPE_PATH = ROOT / "config" / "PROJECT_SCOPE_POLICY.json"
SHARED_DB = ROOT / "data/db/sports_v45.sqlite"
DEDICATED_DBS = {
    "rugby": ROOT / "data/db/rugby_v45.sqlite",
    "boxing": ROOT / "data/db/boxing_v45.sqlite",
}
OUT = ROOT / "results/scope_expansion_state.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_name(scope_id: str) -> str:
    return (
        scope_id.replace("/", "_")
        .replace(":", "__")
        .replace(" ", "_")
    )


def _db_for(sport: str) -> Path:
    path = DEDICATED_DBS.get(sport)
    if path and path.exists():
        return path
    return SHARED_DB


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(r[1]) for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.DatabaseError:
        return set()


def _identity_and_pit(con: sqlite3.Connection, sport: str, events: list[tuple]) -> dict:
    cols = _table_columns(con, "source_snapshot")
    if not cols or "source_available_at_utc" not in cols or "availability_status" not in cols:
        return {"pit_events": 0, "pit_ratio": 0.0, "pit_status": "NO_EXACT_SOURCE_SNAPSHOT_SCHEMA"}

    if not events:
        return {"pit_events": 0, "pit_ratio": 0.0, "pit_status": "NO_EVENTS"}

    qualifying = 0
    for event_id, event_time in events:
        row = con.execute(
            """
            SELECT 1
              FROM source_snapshot ss
             WHERE ss.sport=?
               AND ss.availability_status='EXACT'
               AND ss.source_available_at_utc IS NOT NULL
               AND (
                    (ss.event_time_utc IS NOT NULL AND ss.event_time_utc=?)
                    OR ss.event_time_utc IS NULL
               )
               AND (
                    ss.event_time_utc IS NULL
                    OR ss.source_available_at_utc <= ss.event_time_utc
               )
             LIMIT 1
            """,
            (sport, event_time),
        ).fetchone()
        if row:
            qualifying += 1
    ratio = qualifying / max(len(events), 1)
    return {
        "pit_events": qualifying,
        "pit_ratio": ratio,
        "pit_status": "PASS_RATIO" if ratio >= 0.95 else "PIT_EVIDENCE_INCOMPLETE",
    }


def _metrics_for_events(
    con: sqlite3.Connection,
    sport: str,
    event_filter_sql: str = "",
    event_filter_args: tuple = (),
) -> dict:
    event_rows = con.execute(
        f"""
        SELECT event_id, event_time_utc, competition_id, name
          FROM event
         WHERE sport=? {event_filter_sql}
         ORDER BY event_time_utc, event_id
        """,
        (sport, *event_filter_args),
    ).fetchall()
    verified = con.execute(
        f"""
        SELECT COUNT(*)
          FROM event_outcome o
          JOIN event e ON e.event_id=o.event_id
         WHERE e.sport=?
           AND o.outcome_status='VERIFIED'
           {event_filter_sql}
        """,
        (sport, *event_filter_args),
    ).fetchone()[0]
    pit = _identity_and_pit(con, sport, [(r[0], r[1]) for r in event_rows])
    return {
        "events": len(event_rows),
        "verified_outcomes": int(verified),
        **pit,
    }


def _stage_from_evidence(scope_id: str, evidence: dict | None, metrics: dict, policy: dict) -> tuple[str, list[str]]:
    stages = policy["stage_order"]
    reasons: list[str] = []

    if metrics["events"] <= 0:
        return "METADATA_CHECKED", ["no_historical_events"]
    if metrics["events"] < int(policy["minimums"]["events"]):
        return "METADATA_CHECKED", [f"events<{int(policy['minimums']['events'])}"]
    if metrics["verified_outcomes"] < int(policy["minimums"]["verified_outcomes"]):
        return "DATA_FEASIBLE", [
            f"verified_outcomes<{int(policy['minimums']['verified_outcomes'])}"
        ]
    if metrics["pit_ratio"] < float(policy["minimums"]["exact_pit_event_ratio"]):
        return "DATA_FEASIBLE", [
            f"exact_pit_event_ratio<{float(policy['minimums']['exact_pit_event_ratio']):.2f}"
        ]

    stage = "PIT_VALIDATED"
    evidence = evidence if isinstance(evidence, dict) else {}
    req_map = policy["evidence_requirements"]

    def passed(section: str) -> bool:
        req = req_map[section]
        for key in req["required"]:
            if evidence.get(key) != req["pass_value"]:
                return False
        return True

    if not passed("shadow"):
        return stage, ["shadow_evidence_missing_or_failed"]

    stage = "SHADOW"
    if not passed("oos_robustness"):
        return stage, ["oos_robustness_calibration_or_holdout_evidence_missing_or_failed"]

    stage = "OOS_ROBUSTNESS"
    if not passed("limited_production") or not bool(evidence.get("explicit_scope_admission")):
        return stage, ["limited_production_or_explicit_scope_admission_missing"]

    stage = "LIMITED_PRODUCTION"
    if not passed("stable_production") or int(evidence.get("consecutive_clean_runs", 0)) < int(
        req_map["stable_production"]["minimum_consecutive_clean_runs"]
    ):
        return stage, ["stable_production_evidence_insufficient"]

    stage = "STABLE_PRODUCTION"
    if not passed("scale_up") or int(evidence.get("consecutive_clean_runs", 0)) < int(
        req_map["scale_up"]["minimum_consecutive_clean_runs"]
    ):
        return stage, ["scale_up_evidence_insufficient"]

    return "SCALE_UP", reasons


def candidate_priority(item: dict, policy: dict) -> float:
    stage = str(item.get("stage") or "DISCOVERED")
    order = policy.get("stage_order") or []
    try:
        stage_rank = float(order.index(stage))
    except ValueError:
        stage_rank = 0.0
    metrics = item.get("metrics") or {}
    events = float(metrics.get("events", 0) or 0)
    verified = float(metrics.get("verified_outcomes", 0) or 0)
    pit_ratio = float(metrics.get("pit_ratio", 0.0) or 0.0)
    verified_ratio = verified / max(events, 1.0)
    # Candidate priority is deliberately transparent and conservative:
    # stage readiness dominates, then data/PIT quality and remaining learning value.
    return (
        stage_rank * 1000.0
        + min(events / max(float(policy["minimums"]["events"]), 1.0), 2.0) * 100.0
        + verified_ratio * 100.0
        + pit_ratio * 100.0
    )


def _load_evidence(scope_id: str) -> dict | None:
    path = ROOT / "results/scope_evidence" / f"{_safe_name(scope_id)}.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _active_sports() -> list[str]:
    scope = _load(SCOPE_PATH)
    return [
        str(sport)
        for sport, entries in (scope.get("active_scope") or {}).items()
        if any(
            isinstance(e, dict) and str(e.get("status", "")).upper() == "TARGET"
            for e in entries
        )
    ]


def _active_competition_frontier(con: sqlite3.Connection, sport: str, policy: dict) -> list[dict]:
    rows = con.execute(
        """
        SELECT competition_id, COUNT(*) AS n, SUM(
            CASE WHEN EXISTS (
                SELECT 1
                  FROM event_outcome eo
                 WHERE eo.event_id=event.event_id
                   AND eo.outcome_status='VERIFIED'
            ) THEN 1 ELSE 0 END
        ) AS verified
          FROM event
         WHERE sport=?
           AND competition_id IS NOT NULL
           AND TRIM(competition_id)<>''
         GROUP BY competition_id
         ORDER BY n DESC, competition_id
        """,
        (sport,),
    ).fetchall()

    frontier = []
    for competition_id, event_count, verified in rows:
        profile = resolve_profile(sport, competition_id, None)
        if profile.get("matched"):
            continue
        metrics = _metrics_for_events(
            con,
            sport,
            "AND competition_id=?",
            (competition_id,),
        )
        scope_id = f"{sport}:competition:{competition_id}"
        stage, reasons = _stage_from_evidence(scope_id, _load_evidence(scope_id), metrics, policy)
        frontier.append(
            {
                "scope_id": scope_id,
                "sport": sport,
                "kind": "competition",
                "competition_id": str(competition_id),
                "stage": stage,
                "reasons": reasons,
                "metrics": metrics,
                "priority_score": candidate_priority(
                    {"stage": entry["stage"], "metrics": metrics}, policy
                ),
            }
        )
    return frontier


def main() -> int:
    policy = _load(POLICY_PATH)
    project_scope = _load(PROJECT_SCOPE_PATH)
    active = set(project_scope.get("active_prediction_scope") or [])
    deferred = {
        str(x.get("sport"))
        for x in (policy.get("candidate_sources", {}).get("deferred_sports") or [])
        if isinstance(x, dict)
    }

    state = {
        "version": "staged-scope-expansion-v1",
        "status": "EVALUATED",
        "no_implicit_activation": True,
        "active_prediction_scope": sorted(active),
        "advanced_validation_limit_per_cycle": int(
            policy["limits"]["max_new_targets_in_advanced_validation_per_cycle"]
        ),
        "deferred_sports": {},
        "competition_frontier": {},
        "next_action": "HOLD_UNTIL_EVIDENCE",
    }

    for candidate in policy["candidate_sources"].get("deferred_sports", []):
        sport = str(candidate["sport"])
        scope_id = str(candidate["scope_id"])
        db_path = _db_for(sport)
        entry = {
            "scope_id": scope_id,
            "sport": sport,
            "kind": "sport",
            "active": sport in active,
            "db_path": str(db_path.relative_to(ROOT)) if db_path.exists() else None,
            "evidence_present": _load_evidence(scope_id) is not None,
        }
        if db_path.exists():
            con = sqlite3.connect(db_path)
            try:
                metrics = _metrics_for_events(con, sport)
            finally:
                con.close()
        else:
            metrics = {
                "events": 0,
                "verified_outcomes": 0,
                "pit_events": 0,
                "pit_ratio": 0.0,
                "pit_status": "NO_DATABASE",
            }
        entry["metrics"] = metrics
        entry["stage"], entry["reasons"] = _stage_from_evidence(
            scope_id, _load_evidence(scope_id), metrics, policy
        )
        entry["activation_allowed"] = False
        state["deferred_sports"][sport] = entry

    for sport in sorted(active):
        if not SHARED_DB.exists():
            state["competition_frontier"][sport] = {"status": "NO_SHARED_DB", "candidates": []}
            continue
        con = sqlite3.connect(SHARED_DB)
        try:
            candidates = _active_competition_frontier(con, sport, policy)
        finally:
            con.close()
        state["competition_frontier"][sport] = {
            "status": "EVALUATED",
            "candidate_count": len(candidates),
            "candidates": candidates[:50],
        }

    queued = []
    for sport, item in state["deferred_sports"].items():
        if item["stage"] in {"PIT_VALIDATED", "SHADOW", "OOS_ROBUSTNESS"}:
            queued.append((item["stage"], item["scope_id"]))
    for sport, block in state["competition_frontier"].items():
        for item in block.get("candidates", []):
            if item["stage"] in {"PIT_VALIDATED", "SHADOW", "OOS_ROBUSTNESS"}:
                queued.append((item["stage"], item["scope_id"]))

    queued_items = []
    for stage, scope_id in queued:
        source = None
        if scope_id.startswith("sport:"):
            source = state["deferred_sports"].get(scope_id.split(":", 1)[1])
        else:
            for block in state["competition_frontier"].values():
                for item in block.get("candidates", []):
                    if item.get("scope_id") == scope_id:
                        source = item
                        break
                if source:
                    break
        queued_items.append(
            (
                candidate_priority(source or {"stage": stage, "metrics": {}}, policy),
                scope_id,
            )
        )
    queued_items.sort(key=lambda x: (-x[0], x[1]))
    if queued_items:
        state["next_validation_candidate"] = queued_items[0][1]
        state["advanced_validation_batch"] = [queued_items[0][1]]
        state["next_action"] = "ADVANCE_ONE_CANDIDATE_ONLY"
    else:
        state["next_validation_candidate"] = None
        state["advanced_validation_batch"] = []

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
