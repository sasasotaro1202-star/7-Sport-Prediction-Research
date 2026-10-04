from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ACTIVE_SPORTS = {"basketball", "volleyball", "ufc", "rizin", "valorant"}
WORKFLOWS = {
    "scope_autofill": "scope_autofill.yml",
    "autonomous_research_sweep": "autonomous_research_sweep.yml",
}
ACTIVE_STATES = {"queued", "in_progress", "waiting", "requested", "pending"}
TERMINAL_FAILURES = {"failure", "timed_out", "startup_failure", "cancelled"}
MAX_REPORT_AGE_HOURS = 18.0
MIN_DISPATCH_INTERVAL_HOURS = 5.0


def load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def parse_time(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def age_hours(raw: object, now: datetime) -> float | None:
    dt = parse_time(raw)
    if dt is None:
        return None
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def report_is_fresh(path: Path, commit_time_epoch: int | None, now: datetime) -> bool:
    if not path.is_file() or commit_time_epoch is None:
        return False
    age = max(0.0, now.timestamp() - int(commit_time_epoch)) / 3600.0
    return age <= MAX_REPORT_AGE_HOURS


def active_scope(scope_path: Path) -> set[str]:
    data = load_json(scope_path) or {}
    return {
        sport
        for sport, entries in (data.get("active_scope") or {}).items()
        if sport in ACTIVE_SPORTS
        and isinstance(entries, list)
        and any(isinstance(e, dict) and str(e.get("status", "")).upper() == "TARGET" for e in entries)
    }


def scope_deficit(release_gate: dict | None, quality_gate: dict | None) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    coverage = (release_gate or {}).get("coverage") or {}
    for sport in sorted(ACTIVE_SPORTS):
        row = coverage.get(sport) or {}
        if int(row.get("accepted_models", 0) or 0) == 0:
            reasons.append(f"{sport}:accepted_models=0")
        if str(row.get("model_safety", "")).upper().startswith("DEFERRED:INSUFFICIENT_STRICT_PIT_ROWS"):
            reasons.append(f"{sport}:insufficient_strict_pit_rows")

    pending = (quality_gate or {}).get("pending") or []
    if "no_exact_pit_replay_rows" in pending:
        reasons.append("quality:no_exact_pit_replay_rows")
    if "accepted_model_coverage_incomplete" in pending:
        reasons.append("quality:accepted_model_coverage_incomplete")
    return bool(reasons), reasons


def is_hard_stop_failure(row: dict) -> bool:
    conclusion = str(row.get("conclusion", "")).lower()
    if conclusion not in {"failure", "timed_out", "startup_failure"}:
        return False
    failure_class = str(row.get("failure_class", "")).upper()
    workflow_name = str(row.get("workflow_name", "")).upper()
    # Research-only/shadow failures must not freeze the autonomous research loop.
    hard_markers = ("PRODUCTION", "DATA", "PIT_", "RECOVERY")
    return any(marker in failure_class for marker in hard_markers) or any(
        marker in workflow_name for marker in ("PRODUCTION", "DATA", "PIT", "RECOVERY")
    )


def recent_failure_count(failures: list[dict], now: datetime, hours: float = 6.0) -> int:
    count = 0
    for row in failures:
        if not is_hard_stop_failure(row):
            continue
        recorded = age_hours(row.get("recorded_at_utc"), now)
        if recorded is not None and recorded <= hours:
            count += 1
    return count


def selected_run_state(run_rows: list[dict], main_sha: str, now: datetime) -> dict:
    current = [r for r in run_rows if r.get("headSha") == main_sha]
    active = [r for r in current if r.get("status") in ACTIVE_STATES]
    latest = sorted(
        current,
        key=lambda r: parse_time(r.get("updatedAt") or r.get("createdAt")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    recent = [
        r for r in latest
        if age_hours(r.get("updatedAt") or r.get("createdAt"), now) is not None
        and age_hours(r.get("updatedAt") or r.get("createdAt"), now) <= MIN_DISPATCH_INTERVAL_HOURS
    ]
    return {
        "active": active,
        "recent": recent,
        "latest": latest[:1],
    }


def decide(
    *,
    main_sha: str,
    now: datetime,
    release_gate: dict | None,
    quality_gate: dict | None,
    release_fresh: bool,
    quality_fresh: bool,
    failures: list[dict],
    workflow_runs: dict[str, list[dict]],
    force: bool,
) -> dict:
    action: str
    reason: str
    evidence: dict = {}

    # Manual force may bypass the recent-dispatch cooldown, but never bypasses
    # the hard-stop failure safety gate.
    failure_count = recent_failure_count(failures, now)
    evidence["recent_failure_count_6h"] = failure_count
    if failure_count >= 3:
        return {
            "version": "autonomous-next-action-controller-v1",
            "status": "HOLD",
            "action": None,
            "reason": "three_recent_failures_within_6h",
            "main_sha": main_sha,
            "evidence": evidence,
        }

    fresh_gate = bool(release_fresh and quality_fresh)
    deficit, reasons = scope_deficit(
        release_gate if fresh_gate else None,
        quality_gate if fresh_gate else None,
    )
    evidence["gate_reports_fresh"] = fresh_gate
    # Never expose stale gate-derived deficits as current evidence.
    evidence["scope_deficit_reasons"] = reasons if fresh_gate else []

    if fresh_gate and deficit:
        action = "scope_autofill"
        reason = "active_scope_or_strict_pit_coverage_has_pending_deficits"
    else:
        action = "autonomous_research_sweep"
        reason = "refresh_research_state_without_forcing_production_or_scope_promotion"

    # Cooldown/active-run safety is global across the controller's research
    # workflows. A route change must not allow two research dispatches inside
    # the same bounded interval.
    all_workflow_runs = [
        row
        for rows in workflow_runs.values()
        for row in rows
    ]
    state = selected_run_state(all_workflow_runs, main_sha, now)
    evidence["workflow_state"] = {
        "active": [
            {"databaseId": r.get("databaseId"), "status": r.get("status"), "createdAt": r.get("createdAt")}
            for r in state["active"]
        ],
        "recent_count": len(state["recent"]),
        "latest": state["latest"],
    }

    if state["active"]:
        return {
            "version": "autonomous-next-action-controller-v1",
            "status": "WAIT",
            "action": None,
            "reason": f"{WORKFLOWS[action]} already active on current main",
            "main_sha": main_sha,
            "evidence": evidence,
        }

    if not force and state["recent"]:
        latest = state["recent"][0]
        return {
            "version": "autonomous-next-action-controller-v1",
            "status": "WAIT",
            "action": None,
            "reason": f"{WORKFLOWS[action]} dispatched within the bounded interval",
            "main_sha": main_sha,
            "evidence": evidence,
        }

    return {
        "version": "autonomous-next-action-controller-v1",
        "status": "DISPATCH",
        "action": action,
        "workflow": WORKFLOWS[action],
        "reason": reason,
        "main_sha": main_sha,
        "evidence": evidence,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main-sha", required=True)
    ap.add_argument("--release-gate", type=Path, default=Path("results/release_gate.json"))
    ap.add_argument("--quality-gate", type=Path, default=Path("results/quality_gate.json"))
    ap.add_argument("--failure-memory", type=Path, default=Path("results/failure_memory.jsonl"))
    ap.add_argument("--scope-policy", type=Path, default=Path("config/PROJECT_SCOPE_POLICY.json"))
    ap.add_argument("--release-commit-time", type=int, default=None)
    ap.add_argument("--quality-commit-time", type=int, default=None)
    ap.add_argument("--runs-json-dir", type=Path, required=True)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("results/autonomous_next_action.json"))
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    scope = active_scope(args.scope_policy)
    if scope != ACTIVE_SPORTS:
        raise SystemExit(f"SCOPE_CONTRACT_FAIL expected={sorted(ACTIVE_SPORTS)} observed={sorted(scope)}")

    release_gate = load_json(args.release_gate)
    quality_gate = load_json(args.quality_gate)
    failures = load_jsonl(args.failure_memory)

    release_fresh = report_is_fresh(args.release_gate, args.release_commit_time, now)
    quality_fresh = report_is_fresh(args.quality_gate, args.quality_commit_time, now)

    runs: dict[str, list[dict]] = {}
    for action, workflow in WORKFLOWS.items():
        path = args.runs_json_dir / f"{action}.json"
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            parsed = []
        runs[action] = parsed if isinstance(parsed, list) else []

    decision = decide(
        main_sha=args.main_sha,
        now=now,
        release_gate=release_gate,
        quality_gate=quality_gate,
        release_fresh=release_fresh,
        quality_fresh=quality_fresh,
        failures=failures,
        workflow_runs=runs,
        force=args.force,
    )
    decision["report_freshness"] = {
        "release_gate": release_fresh,
        "quality_gate": quality_fresh,
        "max_age_hours": MAX_REPORT_AGE_HOURS,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
