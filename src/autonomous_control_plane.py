from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ACTIVE_SPORTS = ("valorant", "basketball", "volleyball", "ufc", "rizin")
DEFERRED_SPORTS = ("tennis", "f1", "rugby", "boxing")
ALLOWED_WORKFLOWS = {
    "PIT_COVERAGE_REPAIR": "pit_history_expansion.yml",
    "PRODUCTION_HEARTBEAT": "pre_event_prediction.yml",
    "RESEARCH_HEALTH": "autonomous_research_sweep.yml",
    "DEEP_RESEARCH": "24h_autonomous_research.yml",
    "SOURCE_FEASIBILITY": "source_feasibility_audit.yml",
    "SCOPE_AUTOFILL": "scope_autofill.yml",
    "RUNTIME_HEALTH": "production_runtime_health.yml",
    "SAFETY_AUDIT": "production_safety_audit.yml",
    "LANE_AUDIT": "nine_sport_lane_audit.yml",
    "TRAJECTORY_RESEARCH": "autonomous_temporal_trajectory_loop.yml",
}

MONITORED_WORKFLOWS = {
    "production": "v4_5_15_production.yml",
    "pre_event": "pre_event_prediction.yml",
    "pit_history": "pit_history_expansion.yml",
    "failure_recovery": "production_failure_recovery.yml",
    "research_sweep": "autonomous_research_sweep.yml",
    "watchdog": "production_watchdog.yml",
    "invariants": "production_invariants.yml",
    "lightweight_regression": "lightweight_regression.yml",
    "control_plane_regression": "autonomous_control_plane_regression.yml",
    "trajectory_research": "autonomous_temporal_trajectory_loop.yml",
}
ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "research"
CONTROL_OUT = RESULTS / "autonomous_control_plane.json"
HEALTH_OUT = RESULTS / "automation_health.json"
QUEUE_OUT = RESULTS / "research_queue.jsonl"
ACTION_LOG_OUT = RESULTS / "autonomous_action_log.jsonl"
ACTIONS_SNAPSHOT = ROOT / "results" / "automation_state" / "actions_snapshot.json"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, "MISSING"
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"INVALID:{type(exc).__name__}"
    if not isinstance(obj, dict):
        return None, "WRONG_SHAPE"
    return obj, None


def explicit_int(
    obj: dict[str, Any],
    key: str,
    errors: dict[str, str],
    label: str,
) -> int | None:
    if key not in obj:
        errors[label] = "MISSING"
        return None
    value = obj.get(key)
    if isinstance(value, bool):
        errors[label] = "INVALID"
        return None
    try:
        integer = int(value)
    except (TypeError, ValueError):
        errors[label] = "INVALID"
        return None
    if integer != value:
        errors[label] = "INVALID"
        return None
    return integer


def age_hours(
    payload: dict[str, Any] | None,
    keys: tuple[str, ...],
    ref: datetime,
) -> float | None:
    if not payload:
        return None
    for key in keys:
        dt = parse_dt(payload.get(key))
        if dt is not None:
            return max(0.0, (ref - dt).total_seconds() / 3600.0)
    return None


def fingerprint(*parts: Any) -> str:
    raw = "|".join("" if x is None else str(x) for x in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def queue_fingerprints() -> set[str]:
    if not QUEUE_OUT.exists():
        return set()
    out: set[str] = set()
    for line in QUEUE_OUT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError("RESEARCH_QUEUE_INVALID_JSONL") from exc
        if isinstance(row, dict) and row.get("fingerprint"):
            out.add(str(row["fingerprint"]))
    return out


def load_actions_snapshot() -> tuple[dict[str, Any], dict[str, str]]:
    if not ACTIONS_SNAPSHOT.exists():
        return {}, {"actions_snapshot": "MISSING"}
    try:
        payload = json.loads(ACTIONS_SNAPSHOT.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, {"actions_snapshot": f"INVALID:{type(exc).__name__}"}
    if not isinstance(payload, dict):
        return {}, {"actions_snapshot": "WRONG_SHAPE"}
    errors = payload.get("errors")
    if errors is None:
        errors = {}
    if not isinstance(errors, dict):
        errors = {"actions_snapshot.errors": "INVALID"}
    workflows = payload.get("workflows")
    if not isinstance(workflows, dict):
        return {}, {**errors, "actions_snapshot.workflows": "MISSING_OR_INVALID"}
    return workflows, {str(k): str(v) for k, v in errors.items()}


def action_health(
    workflows: dict[str, Any],
    workflow: str,
    max_age_hours: float,
    current_main_sha: str | None = None,
) -> dict[str, Any]:
    raw = workflows.get(workflow)
    if not isinstance(raw, dict):
        return {
            "status": "MISSING",
            "age_hours": None,
            "head_sha": None,
            "conclusion": None,
            "run_id": None,
            "stale": True,
        }
    latest = raw.get("latest")
    recent = raw.get("recent")
    if not isinstance(recent, list):
        recent = []
    active_statuses = {"queued", "in_progress", "waiting", "requested", "pending"}
    active_run_any = any(
        isinstance(run, dict) and str(run.get("status") or "") in active_statuses
        for run in recent
    )
    if not isinstance(latest, dict):
        return {
            "status": "MISSING",
            "age_hours": None,
            "head_sha": None,
            "conclusion": None,
            "run_id": None,
            "active_run_any": active_run_any,
            "stale": True,
        }
    created = parse_dt(latest.get("createdAt"))
    age = None
    if created is not None:
        age = max(0.0, (now_utc() - created).total_seconds() / 3600.0)
    conclusion = str(latest.get("conclusion") or "")
    run_status = str(latest.get("status") or "")
    head_sha = str(latest.get("headSha") or "")
    sha_provenance_missing = (
        not current_main_sha
        or current_main_sha == "UNKNOWN"
        or not head_sha
    )
    sha_mismatch = bool(
        not sha_provenance_missing
        and head_sha != current_main_sha
    )
    healthy = (
        conclusion == "success"
        and run_status == "completed"
        and age is not None
        and age <= max_age_hours
        and not sha_provenance_missing
        and not sha_mismatch
    )
    return {
        "run_status": run_status,
        "status": "STALE" if sha_provenance_missing or sha_mismatch else (
            "HEALTHY" if healthy else (
                "FAILED" if conclusion in {"failure", "timed_out", "startup_failure", "cancelled"} else
                ("STALE" if age is None or age > max_age_hours else "IN_PROGRESS")
            )
        ),
        "age_hours": age,
        "head_sha": latest.get("headSha"),
        "current_main_sha": current_main_sha,
        "sha_match": None if not current_main_sha or current_main_sha == "UNKNOWN" or not head_sha else not sha_mismatch,
        "conclusion": conclusion or None,
        "run_id": latest.get("databaseId"),
        "active_run_any": active_run_any,
        "stale": (not healthy) or sha_mismatch,
    }


def load_failure_memory() -> tuple[dict[str, Any], dict[str, str]]:
    path = RESULTS.parent / "failure_memory.jsonl"
    if not path.exists():
        return {
            "records_total": 0,
            "recent_24h": 0,
            "recent_7d": 0,
            "latest": None,
            "latest_failure_at_utc": None,
            "by_class_recent_24h": {},
            "status": "MISSING",
        }, {"failure_memory": "MISSING"}

    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return {
            "records_total": 0,
            "recent_24h": 0,
            "recent_7d": 0,
            "latest": None,
            "latest_failure_at_utc": None,
            "by_class_recent_24h": {},
            "status": "UNREADABLE",
        }, {"failure_memory": f"UNREADABLE:{type(exc).__name__}"}

    for idx, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors[f"failure_memory.line_{idx}"] = f"INVALID_JSON:{exc}"
            continue
        if not isinstance(obj, dict):
            errors[f"failure_memory.line_{idx}"] = "WRONG_SHAPE"
            continue
        rows.append(obj)

    now = now_utc()
    recent_24h_rows: list[dict[str, Any]] = []
    recent_7d_rows: list[dict[str, Any]] = []
    parsed_rows: list[tuple[datetime, dict[str, Any]]] = []
    for obj in rows:
        dt = parse_dt(obj.get("recorded_at_utc"))
        if dt is None:
            errors[f"failure_memory.recorded_at_utc.{obj.get('record_id', 'unknown')}"] = "MISSING_OR_INVALID"
            continue
        parsed_rows.append((dt, obj))
        age_hours_value = max(0.0, (now - dt).total_seconds() / 3600.0)
        if age_hours_value <= 24.0:
            recent_24h_rows.append(obj)
        if age_hours_value <= 168.0:
            recent_7d_rows.append(obj)

    parsed_rows.sort(key=lambda pair: pair[0], reverse=True)
    latest = parsed_rows[0][1] if parsed_rows else None
    by_class: dict[str, int] = {}
    for obj in recent_24h_rows:
        failure_class = str(obj.get("failure_class") or "UNKNOWN")
        by_class[failure_class] = by_class.get(failure_class, 0) + 1

    return {
        "records_total": len(rows),
        "recent_24h": len(recent_24h_rows),
        "recent_7d": len(recent_7d_rows),
        "latest": latest,
        "latest_failure_at_utc": parsed_rows[0][0].isoformat() if parsed_rows else None,
        "by_class_recent_24h": dict(sorted(by_class.items())),
        "status": "OK" if not errors else "DEGRADED",
    }, errors

def inspect() -> dict[str, Any]:
    ref = now_utc()
    actions, action_errors = load_actions_snapshot()
    files = {
        "release_gate": RESULTS.parent / "release_gate.json",
        "quality_gate": RESULTS.parent / "quality_gate.json",
        "future_predictions": RESULTS.parent / "future_predictions.json",
        "experience_summary": RESULTS.parent / "experience_summary.json",
        "route_observability": RESULTS / "production_route_observability.json",
        "timing_routes": RESULTS / "timing_routes.json",
        "reproducibility_manifest": RESULTS.parent / "reproducibility_manifest.json",
        "dual_learning": RESULTS / "dual_learning_cycle.json",
    }
    payloads: dict[str, dict[str, Any] | None] = {}
    errors: dict[str, str] = {}
    for name, path in files.items():
        obj, err = load_json(path)
        payloads[name] = obj
        if err:
            errors[name] = err

    release = payloads["release_gate"] or {}
    quality = payloads["quality_gate"] or {}
    future = payloads["future_predictions"] or {}
    experience = payloads["experience_summary"] or {}
    routes = payloads["route_observability"] or {}
    timing = payloads["timing_routes"] or {}
    repro = payloads["reproducibility_manifest"] or {}
    failure_memory, failure_memory_errors = load_failure_memory()

    head_sha = os.environ.get("GITHUB_SHA") or "UNKNOWN"

    event_workflow = os.environ.get("CONTROL_PLANE_EVENT_WORKFLOW", "")
    event_conclusion = os.environ.get("CONTROL_PLANE_EVENT_CONCLUSION", "")
    event_head_sha = os.environ.get("CONTROL_PLANE_EVENT_HEAD_SHA", "")
    event_run_id = os.environ.get("CONTROL_PLANE_EVENT_RUN_ID", "")
    event_ancestor_of_main = os.environ.get("CONTROL_PLANE_EVENT_ANCESTOR_OF_MAIN", "").lower() == "true"
    event_target = next((
        target for target, workflow in MONITORED_WORKFLOWS.items()
        if workflow == event_workflow
    ), None)
    if not event_workflow:
        event_relation = "NONE"
    elif event_head_sha and event_head_sha == head_sha:
        event_relation = "SAME_CURRENT_MAIN"
    elif event_ancestor_of_main:
        event_relation = "ANCESTOR_OF_CURRENT_MAIN"
    else:
        event_relation = "UNVERIFIED_OR_DIVERGED"
    event_evidence = {
        "workflow": event_workflow or None,
        "conclusion": event_conclusion or None,
        "head_sha": event_head_sha or None,
        "run_id": event_run_id or None,
        "target": event_target,
        "relation_to_current_main": event_relation,
        "ancestor_of_current_main": event_ancestor_of_main,
        "eligible": bool(
            event_target is not None
            and event_conclusion in {"failure", "timed_out", "startup_failure", "cancelled"}
            and bool(event_head_sha)
            and event_relation in {"SAME_CURRENT_MAIN", "ANCESTOR_OF_CURRENT_MAIN"}
        ),
    }

    for key, value in action_errors.items():
        errors[key] = value
    for key, value in failure_memory_errors.items():
        errors[key] = value
    action_summary = {
        "source_feasibility": action_health(actions, "source_feasibility_audit.yml", 4.5, current_main_sha=head_sha),
        "scope_autofill": action_health(actions, "scope_autofill.yml", 7.0, current_main_sha=head_sha),
        "runtime_health": action_health(actions, "production_runtime_health.yml", 1.5, current_main_sha=head_sha),
        "safety_audit": action_health(actions, "production_safety_audit.yml", 4.5, current_main_sha=head_sha),
        "lane_audit": action_health(actions, "nine_sport_lane_audit.yml", 7.5, current_main_sha=head_sha),
        "research_sweep": action_health(actions, "autonomous_research_sweep.yml", 7.0, current_main_sha=head_sha),
        "deep_research": action_health(actions, "24h_autonomous_research.yml", 26.0, current_main_sha=head_sha),
        "pre_event_prediction": action_health(actions, "pre_event_prediction.yml", 0.5, current_main_sha=head_sha),
        "production": action_health(actions, MONITORED_WORKFLOWS["production"], 1.5, current_main_sha=head_sha),
        "pit_history": action_health(actions, MONITORED_WORKFLOWS["pit_history"], 12.0, current_main_sha=head_sha),
        "failure_recovery": action_health(actions, MONITORED_WORKFLOWS["failure_recovery"], 12.0, current_main_sha=head_sha),
        "watchdog": action_health(actions, MONITORED_WORKFLOWS["watchdog"], 0.5, current_main_sha=head_sha),
        "invariants": action_health(actions, MONITORED_WORKFLOWS["invariants"], 4.5, current_main_sha=head_sha),
        "lightweight_regression": action_health(actions, MONITORED_WORKFLOWS["lightweight_regression"], 4.5, current_main_sha=head_sha),
        "control_plane_regression": action_health(actions, MONITORED_WORKFLOWS["control_plane_regression"], 4.5, current_main_sha=head_sha),
        "trajectory_research": action_health(actions, MONITORED_WORKFLOWS["trajectory_research"], 2.0, current_main_sha=head_sha),
    }

    coverage = release.get("coverage")
    if not isinstance(coverage, dict):
        coverage = {}
        errors["release_gate.coverage"] = "MISSING_OR_INVALID"

    accepted_model_gap: list[str] = []
    for sport in ACTIVE_SPORTS:
        entry = coverage.get(sport)
        if not isinstance(entry, dict):
            errors[f"release_gate.coverage.{sport}"] = "MISSING_OR_INVALID"
            continue
        accepted = explicit_int(
            entry,
            "accepted_models",
            errors,
            f"release_gate.coverage.{sport}.accepted_models",
        )
        if accepted is not None and accepted == 0:
            accepted_model_gap.append(sport)

    checks = quality.get("checks")
    if not isinstance(checks, list):
        checks = []
        errors["quality_gate.checks"] = "MISSING_OR_INVALID"

    pit_check = next(
        (x for x in checks if isinstance(x, dict) and x.get("check") == "pit_leakage"),
        None,
    )
    if pit_check is None:
        pit_exact = None
        errors["quality_gate.pit_leakage"] = "MISSING"
    else:
        pit_exact = explicit_int(
            pit_check,
            "exact_pass",
            errors,
            "quality_gate.pit_leakage.exact_pass",
        )
    pending = quality.get("pending")
    if pending is None:
        pending = []
    if not isinstance(pending, list):
        errors["quality_gate.pending"] = "INVALID"
        pending = []
    pit_pending = (
        "no_exact_pit_replay_rows" in set(pending)
        or pit_exact is None
        or pit_exact == 0
    )

    future_generated = future.get("generated_at_utc")
    future_age = age_hours(future, ("generated_at_utc",), ref)
    future_age_class = (
        "MISSING"
        if future_age is None
        else ("FRESH" if future_age < 0.75 else "STALE")
    )
    sports_field = future.get("sports")
    if not isinstance(sports_field, list):
        errors["future_predictions.sports"] = "MISSING_OR_INVALID"
        future_statuses: set[str] = set()
    else:
        future_statuses = {
            str(x.get("status") or "UNKNOWN")
            for x in sports_field
            if isinstance(x, dict)
        }

    manifest_sha = str(repro.get("source_git_commit_sha") or "")
    repro_match = bool(head_sha != "UNKNOWN" and manifest_sha and head_sha == manifest_sha)

    def observed_int(
        parent: dict[str, Any],
        key: str,
        label: str,
    ) -> int | None:
        return explicit_int(parent, key, errors, label)

    experience_archive = observed_int(
        experience,
        "prediction_archive_total",
        "experience_summary.prediction_archive_total",
    )
    experience_scored = observed_int(
        experience,
        "resolved_scored_total",
        "experience_summary.resolved_scored_total",
    )
    experience_unresolved = observed_int(
        experience,
        "unresolved_total",
        "experience_summary.unresolved_total",
    )

    route_source = routes.get("source")
    if not isinstance(route_source, dict):
        route_source = {}
        errors["production_route_observability.source"] = "MISSING_OR_INVALID"
    route_registry = routes.get("route_registry")
    if not isinstance(route_registry, dict):
        route_registry = {}
        errors["production_route_observability.route_registry"] = "MISSING_OR_INVALID"
    timing_registry = routes.get("timing_registry")
    if not isinstance(timing_registry, dict):
        timing_registry = {}
        errors["production_route_observability.timing_registry"] = "MISSING_OR_INVALID"

    return {
        "observed_at_utc": ref.isoformat(),
        "head_sha": head_sha,
        "reproducibility": {
            "manifest_sha": manifest_sha or None,
            "head_matches_manifest": repro_match,
            "status": (
                "MATCH"
                if repro_match
                else ("UNKNOWN" if head_sha == "UNKNOWN" else "STALE_OR_MISSING")
            ),
        },
        "errors": errors,
        "quality": {
            "status": quality.get("status", "UNKNOWN"),
            "pending": pending,
            "pit_exact_pass": pit_exact,
            "pit_research_blocked": pit_pending,
        },
        "release": {
            "status": release.get("status", "UNKNOWN"),
            "publish": release.get("publish") if "publish" in release else None,
            "active_accepted_model_gap": accepted_model_gap,
        },
        "future_prediction": {
            "generated_at_utc": future_generated,
            "age_hours": future_age,
            "age_class": future_age_class,
            "statuses": sorted(future_statuses),
        },
        "experience": {
            "archive_total": experience_archive,
            "scored_total": experience_scored,
            "unresolved_total": experience_unresolved,
            "generated_at_utc": experience.get("generated_at_utc"),
        },
        "route_observability": {
            "prediction_rows": observed_int(
                route_source, "prediction_rows", "production_route_observability.source.prediction_rows"
            ),
            "accepted_routes": observed_int(
                route_registry,
                "accepted_route_count",
                "production_route_observability.route_registry.accepted_route_count",
            ),
            "accepted_timing_routes": observed_int(
                timing_registry,
                "accepted_route_count",
                "production_route_observability.timing_registry.accepted_route_count",
            ),
        },
        "timing": {
            "status": timing.get("status", "UNKNOWN"),
            "route_count": len(timing.get("routes") or {}) if isinstance(timing.get("routes") or {}, dict) else None,
        },
        "actions": action_summary,
        "event_evidence": event_evidence,
        "failure_memory": failure_memory,
        "dual_learning": {
            "status": (payloads["dual_learning"] or {}).get("status", "UNKNOWN"),
            "generated_at_utc": (payloads["dual_learning"] or {}).get("finished_at_utc"),
        },
    }


def choose_actions(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    candidates: list[dict[str, Any]] = []
    workflow_health_target = {
        ALLOWED_WORKFLOWS["RESEARCH_HEALTH"]: "research_sweep",
        ALLOWED_WORKFLOWS["DEEP_RESEARCH"]: "deep_research",
        ALLOWED_WORKFLOWS["SOURCE_FEASIBILITY"]: "source_feasibility",
        ALLOWED_WORKFLOWS["SCOPE_AUTOFILL"]: "scope_autofill",
        ALLOWED_WORKFLOWS["RUNTIME_HEALTH"]: "runtime_health",
        ALLOWED_WORKFLOWS["SAFETY_AUDIT"]: "safety_audit",
        ALLOWED_WORKFLOWS["LANE_AUDIT"]: "lane_audit",
        ALLOWED_WORKFLOWS["TRAJECTORY_RESEARCH"]: "trajectory_research",
        ALLOWED_WORKFLOWS["PRODUCTION_HEARTBEAT"]: "pre_event_prediction",
    }

    # A workflow_run failure is first-class evidence. inspect() has already
    # validated the event against current main or a verified ancestor.
    event_evidence = state.get("event_evidence") or {}
    if event_evidence.get("eligible"):
        event_target = str(event_evidence.get("target") or "UNKNOWN")
        candidates.append({
            "action": "RESEARCH_HEALTH",
            "workflow": ALLOWED_WORKFLOWS["RESEARCH_HEALTH"],
            "target": f"workflow_event_failure:{event_target}",
            "impact": 28.0,
            "evidence_gap": 1.0,
            "failure_relevance": 1.0,
            "generalization": 1.0,
            "information_value": 1.0,
            "cost": 1.0,
            "reason": (
                f"workflow_run reported {event_evidence.get('conclusion')} for "
                f"monitored workflow {event_evidence.get('target')}; event relation="
                f"{event_evidence.get('relation_to_current_main')}; use event evidence "
                "directly before later snapshot rows can mask the triggering failure"
            ),
            "auto_dispatch": True,
            "dispatch_policy": "event_payload_first_failure_triage_on_current_main_or_ancestor_sha",
        })

    if state["quality"]["pit_research_blocked"]:
        candidates.append({
            "action": "PIT_COVERAGE_REPAIR",
            "workflow": ALLOWED_WORKFLOWS["PIT_COVERAGE_REPAIR"],
            "target": "active_scope",
            "impact": 100.0,
            "evidence_gap": 1.0,
            "failure_relevance": 1.0,
            "generalization": 1.0,
            "information_value": 1.0,
            "cost": 1.0,
            "reason": "exact PIT evidence is absent, explicitly pending, or unresolvable; production-grade OOS cannot advance safely",
            "auto_dispatch": False,
            "dispatch_policy": "respect_fixed_pit_boundary_or_existing_watchdog",
        })

    if state["future_prediction"]["age_class"] in {"MISSING", "STALE"}:
        candidates.append({
            "action": "PRODUCTION_HEARTBEAT",
            "workflow": ALLOWED_WORKFLOWS["PRODUCTION_HEARTBEAT"],
            "target": "active_scope",
            "impact": 18.0,
            "evidence_gap": 0.8,
            "failure_relevance": 0.8,
            "generalization": 0.9,
            "information_value": 0.9,
            "cost": 1.0,
            "reason": "future-prediction evidence is missing or stale relative to the autonomous heartbeat",
            "auto_dispatch": False,
            "dispatch_policy": "existing_production_watchdog_owns_heartbeat_recovery",
        })

    actions = state.get("actions") or {}

    def add_maintenance_action(
        action: str,
        target: str,
        priority_base: float,
        reason: str,
    ) -> None:
        health = actions.get(target) or {}
        if health.get("stale"):
            candidates.append({
                "action": action,
                "workflow": ALLOWED_WORKFLOWS[action],
                "target": target,
                "impact": priority_base,
                "evidence_gap": 0.8,
                "failure_relevance": 0.8 if health.get("status") == "FAILED" else 0.6,
                "generalization": 0.8,
                "information_value": 0.8,
                "cost": 1.0,
                "reason": reason,
                "auto_dispatch": True,
                "dispatch_policy": "bounded_recovery_when_missing_stale_or_failed",
            })

    add_maintenance_action(
        "SOURCE_FEASIBILITY",
        "source_feasibility",
        17.0,
        "active/deferred source feasibility evidence is missing, stale, or failed",
    )
    add_maintenance_action(
        "SCOPE_AUTOFILL",
        "scope_autofill",
        13.0,
        "scope discovery/autofill heartbeat is missing, stale, or failed",
    )
    add_maintenance_action(
        "RUNTIME_HEALTH",
        "runtime_health",
        19.0,
        "production runtime health evidence is missing, stale, or failed",
    )
    add_maintenance_action(
        "SAFETY_AUDIT",
        "safety_audit",
        18.0,
        "production safety audit evidence is missing, stale, or failed",
    )
    add_maintenance_action(
        "LANE_AUDIT",
        "lane_audit",
        11.0,
        "nine-sport lane audit evidence is missing, stale, or failed",
    )

    add_maintenance_action(
        "TRAJECTORY_RESEARCH",
        "trajectory_research",
        21.0,
        "temporal trajectory collection/research heartbeat is missing, stale, or failed",
    )

    # Snapshot-only fallback covers failures observed between event delivery
    # and the next snapshot refresh. SHA match is mandatory.
    for monitored_target in (
        "pre_event",
        "production",
        "pit_history",
        "failure_recovery",
        "control_plane_regression",
        "trajectory_research",
    ):
        health = state["actions"].get(monitored_target) or {}
        age = health.get("age_hours")
        if (
            health.get("status") == "FAILED"
            and state["head_sha"] != "UNKNOWN"
            and health.get("head_sha") == state["head_sha"]
            and isinstance(age, (int, float))
            and age <= 24.0
        ):
            candidates.append({
                "action": "RESEARCH_HEALTH",
                "workflow": ALLOWED_WORKFLOWS["RESEARCH_HEALTH"],
                "target": f"workflow_failure:{monitored_target}",
                "impact": 26.0,
                "evidence_gap": 1.0,
                "failure_relevance": 1.0,
                "generalization": 1.0,
                "information_value": 1.0,
                "cost": 1.0,
                "reason": (
                    f"current-main monitored workflow {monitored_target} failed within "
                    "the last 24 hours; triage without waiting for Failure Memory persistence"
                ),
                "auto_dispatch": True,
                "dispatch_policy": "event_driven_failure_triage_on_current_main_sha",
            })

    if state.get("failure_memory", {}).get("recent_24h", 0) > 0:
        candidates.append({
            "action": "RESEARCH_HEALTH",
            "workflow": ALLOWED_WORKFLOWS["RESEARCH_HEALTH"],
            "target": "recent_failures",
            "impact": 24.0,
            "evidence_gap": 0.95,
            "failure_relevance": 1.0,
            "generalization": 1.0,
            "information_value": 0.95,
            "cost": 1.0,
            "reason": "recent production/research failures are recorded in Failure Memory; convert observed failures into bounded root-cause research before performance changes",
            "auto_dispatch": True,
            "dispatch_policy": "bounded_failure-followup_when_recent_failure_memory_exists",
        })
    if state["release"]["active_accepted_model_gap"]:
        candidates.append({
            "action": "DEEP_RESEARCH",
            "workflow": ALLOWED_WORKFLOWS["DEEP_RESEARCH"],
            "target": ",".join(state["release"]["active_accepted_model_gap"]),
            "impact": 24.0,
            "evidence_gap": 0.95,
            "failure_relevance": 0.85,
            "generalization": 1.0,
            "information_value": 0.9,
            "cost": 2.0,
            "reason": "active sports lack accepted models based on explicit release-gate evidence; continue chronological/OOS research without automatic production promotion",
            "auto_dispatch": True,
            "dispatch_policy": "only_when_no_current_run_and_heavy_research_cooldown_elapsed",
        })

    if state["errors"] or state["reproducibility"]["status"] != "MATCH":
        candidates.append({
            "action": "RESEARCH_HEALTH",
            "workflow": ALLOWED_WORKFLOWS["RESEARCH_HEALTH"],
            "target": "evidence_integrity",
            "impact": 15.0,
            "evidence_gap": 0.9,
            "failure_relevance": 0.9,
            "generalization": 0.8,
            "information_value": 0.8,
            "cost": 1.0,
            "reason": "evidence is incomplete, malformed, or provenance-stale; reconcile health without treating missing values as zero",
            "auto_dispatch": True,
            "dispatch_policy": "only_when_no_current_run_and_health_cooldown_elapsed",
        })

    candidates.append({
        "action": "RESEARCH_HEALTH",
        "workflow": ALLOWED_WORKFLOWS["RESEARCH_HEALTH"],
        "target": "general",
        "impact": 5.0,
        "evidence_gap": 0.4,
        "failure_relevance": 0.4,
        "generalization": 0.9,
        "information_value": 0.8,
        "cost": 1.0,
        "reason": "no higher-priority blocker selected; continue bounded autonomous research health sweep",
        "auto_dispatch": True,
        "dispatch_policy": "only_when_no_current_run_and_health_cooldown_elapsed",
    })

    for c in candidates:
        c["priority"] = round(
            c["impact"]
            * c["evidence_gap"]
            * c["failure_relevance"]
            * c["generalization"]
            * c["information_value"]
            / c["cost"],
            6,
        )

        health_target = workflow_health_target.get(c.get("workflow"))
        health = actions.get(health_target) if health_target else None
        if c.get("auto_dispatch") and isinstance(health, dict) and health.get("active_run_any"):
            c["auto_dispatch"] = False
            c["dispatch_block_reason"] = (
                "target_workflow_already_has_an_active_run_in_recent_actions_snapshot"
            )

    candidates.sort(key=lambda c: (-float(c["priority"]), str(c["action"]), str(c["target"])))
    selected = dict(candidates[0])
    selected["status"] = "QUEUE_ONLY" if not selected["auto_dispatch"] else "DISPATCH_CANDIDATE"
    selected["automatic_promotion"] = False
    selected["selection_rule"] = "max(priority) with deterministic action/target tie-break"

    dispatchable = [c for c in candidates if c.get("auto_dispatch")]
    dispatch = dict(dispatchable[0]) if dispatchable else None
    if dispatch is not None:
        dispatch["status"] = "DISPATCH_CANDIDATE"
        dispatch["automatic_promotion"] = False
    return selected, dispatch


def state_fingerprint(
    state: dict[str, Any],
    selected: dict[str, Any],
    dispatch: dict[str, Any] | None,
) -> str:
    future = state["future_prediction"]
    experience = state["experience"]
    dual = state["dual_learning"]
    action_fingerprint = {}
    for name, raw in (state.get("actions") or {}).items():
        if isinstance(raw, dict):
            # Fingerprint only stable workflow-run evidence. The current main SHA,
            # freshness age, derived health status, and SHA-match fields are
            # invocation-relative metadata and must not self-trigger a commit.
            action_fingerprint[name] = {
                key: raw.get(key)
                for key in ("run_status", "head_sha", "conclusion", "run_id")
            }
        else:
            action_fingerprint[name] = raw

    normalized = {
        "errors": state["errors"],
        "quality": state["quality"],
        "release": state["release"],
        "future_prediction": {
            "generated_at_utc": future["generated_at_utc"],
            "age_class": future["age_class"],
            "statuses": future["statuses"],
        },
        "experience": {
            "archive_total": experience["archive_total"],
            "scored_total": experience["scored_total"],
            "unresolved_total": experience["unresolved_total"],
            "generated_at_utc": experience["generated_at_utc"],
        },
        "route_observability": state["route_observability"],
        "timing": state["timing"],
        "actions": action_fingerprint,
        "event_evidence": {
            key: (state.get("event_evidence") or {}).get(key)
            for key in (
                "workflow",
                "conclusion",
                "head_sha",
                "run_id",
                "target",
                "relation_to_current_main",
            )
        },
        "failure_memory": state.get("failure_memory"),
        "dual_learning": dual,
        "selected": {
            "action": selected["action"],
            "workflow": selected["workflow"],
            "target": selected["target"],
            "priority": selected["priority"],
        },
        "dispatch": None if dispatch is None else {
            "action": dispatch["action"],
            "workflow": dispatch["workflow"],
            "target": dispatch["target"],
            "priority": dispatch["priority"],
        },
    }
    return fingerprint(json.dumps(normalized, sort_keys=True, ensure_ascii=False))


def write_state(
    state: dict[str, Any],
    selected: dict[str, Any],
    dispatch: dict[str, Any] | None,
) -> dict[str, Any]:
    RESULTS.mkdir(parents=True, exist_ok=True)
    fp = state_fingerprint(state, selected, dispatch)
    previous, _ = load_json(CONTROL_OUT)
    previous_fp = previous.get("state_fingerprint") if previous else None

    selected = dict(selected)
    selected["fingerprint"] = fingerprint(
        fp, selected["action"], selected["target"], selected["reason"]
    )
    queue_ids = queue_fingerprints()
    queue_added = selected["fingerprint"] not in queue_ids
    if queue_added:
        with QUEUE_OUT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "queued_at_utc": state["observed_at_utc"],
                "head_sha": state["head_sha"],
                **selected,
            }, ensure_ascii=False, sort_keys=True) + "\n")

    should_write = previous_fp != fp or not CONTROL_OUT.exists() or not HEALTH_OUT.exists()
    if previous_fp != fp or not ACTION_LOG_OUT.exists():
        action_record = {
            "recorded_at_utc": state["observed_at_utc"],
            "head_sha": state["head_sha"],
            "state_fingerprint": fp,
            "selected_action": selected,
            "dispatch_action": dispatch,
            "automatic_promotion": False,
        }
        ACTION_LOG_OUT.parent.mkdir(parents=True, exist_ok=True)
        with ACTION_LOG_OUT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(action_record, ensure_ascii=False, sort_keys=True) + "\n")
    if should_write:
        control = {
            "version": "autonomous-control-plane-v1",
            "generated_at_utc": state["observed_at_utc"],
            "head_sha": state["head_sha"],
            "state_fingerprint": fp,
            "status": "DEGRADED" if state["errors"] or state["reproducibility"]["status"] != "MATCH" else "READY",
            "active_sports": list(ACTIVE_SPORTS),
            "deferred_sports": list(DEFERRED_SPORTS),
            "observations": state,
            "selected_action": selected,
            "dispatch_action": dispatch,
            "automatic_promotion": False,
            "queue": {
                "fingerprint": selected["fingerprint"],
                "added": queue_added,
                "previous_state_fingerprint": previous_fp,
            },
            "allowed_workflows": ALLOWED_WORKFLOWS,
            "safety": {
                "no_model_auto_promotion": True,
                "no_frozen_holdout_tuning": True,
                "pit_fail_closed": True,
                "missing_not_zero": True,
                "single_writer": True,
                "main_sha_recheck_required_before_push": True,
                "actions_snapshot_is_provenance_input": True,
                "automatic_dispatch_is_bounded_and_allowlisted": True,
                "state_fingerprint_excludes_invocation_sha": True,
                "state_fingerprint_excludes_volatile_action_age": True,
                "state_fingerprint_excludes_derived_current_main_metadata": True,
                "action_log_appends_only_on_decision_change": True,
            },
        }
        CONTROL_OUT.write_text(json.dumps(control, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        HEALTH_OUT.write_text(json.dumps({
            "version": "automation-health-v1",
            "generated_at_utc": state["observed_at_utc"],
            "head_sha": state["head_sha"],
            "control_plane_status": control["status"],
            "selected_action": selected["action"],
            "selected_workflow": selected["workflow"],
            "dispatch_candidate": None if dispatch is None else dispatch["action"],
            "automatic_promotion": False,
            "reproducibility_status": state["reproducibility"]["status"],
            "pit_exact_pass": state["quality"]["pit_exact_pass"],
            "queue_entry_added": queue_added,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "state_fingerprint": fp,
        "selected": selected,
        "dispatch": dispatch,
        "write_needed": should_write,
        "queue_added": queue_added,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic GitHub-native research control plane")
    ap.add_argument("--head-sha", default=os.environ.get("GITHUB_SHA", "UNKNOWN"))
    args = ap.parse_args()
    os.environ["GITHUB_SHA"] = str(args.head_sha)

    state = inspect()
    selected, dispatch = choose_actions(state)
    persisted = write_state(state, selected, dispatch)
    print(json.dumps({
        "status": "DISPATCH_CANDIDATE",
        "head_sha": args.head_sha,
        "selected_action": persisted["selected"],
        "dispatch_action": persisted["dispatch"],
        "write_needed": persisted["write_needed"],
        "queue_added": persisted["queue_added"],
        "automatic_promotion": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())