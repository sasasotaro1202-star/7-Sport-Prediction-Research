from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKFLOW = "v4_5_15_production.yml"
DEFAULT_OUT = ROOT / "results/research/production_runtime_health.json"
LONG_RUNNING_MINUTES = 90
STALE_RISK_MINUTES = 240


def _utc(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def elapsed_minutes(started_at: Any, now: datetime) -> float | None:
    ts = _utc(started_at)
    if ts is None:
        return None
    return max(0.0, (now - ts).total_seconds() / 60.0)


def classify_run(status: str, conclusion: str | None, elapsed: float | None) -> str:
    status = str(status or "unknown").strip().lower()
    conclusion = str(conclusion or "").strip().lower()
    if status == "completed":
        if conclusion == "success":
            return "SUCCESS"
        if conclusion == "cancelled":
            return "CANCELLED"
        if conclusion in {"failure", "timed_out", "action_required"}:
            return "FAILURE"
        return "TERMINAL"
    if status in {"queued", "requested", "waiting", "pending"}:
        return "QUEUED"
    if status == "in_progress":
        if elapsed is None:
            return "RUNNING"
        if elapsed >= STALE_RISK_MINUTES:
            return "STALE_RISK"
        if elapsed >= LONG_RUNNING_MINUTES:
            return "LONG_RUNNING"
        return "RUNNING"
    return "UNKNOWN"


def classify_job(job: dict[str, Any]) -> str:
    status = str(job.get("status") or "unknown").strip().lower()
    conclusion = str(job.get("conclusion") or "").strip().lower()
    if status == "completed":
        if conclusion == "success":
            return "SUCCESS"
        if conclusion == "cancelled":
            return "CANCELLED"
        if conclusion in {"failure", "timed_out", "action_required"}:
            return "FAILURE"
        return "TERMINAL"
    if status == "in_progress":
        return "RUNNING"
    if status in {"queued", "waiting", "pending"}:
        return "QUEUED"
    return "UNKNOWN"


def _api_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "7-Sport-Prediction-Research-runtime-health",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            value = json.load(response)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise RuntimeError(f"GITHUB_API_LOOKUP_FAILED:{type(exc).__name__}:{exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("GITHUB_API_INVALID_OBJECT")
    return value


def _latest_production_run(api_base: str, repository: str, token: str, workflow: str) -> dict[str, Any]:
    url = f"{api_base}/repos/{repository}/actions/workflows/{workflow}/runs?branch=main&per_page=10"
    payload = _api_json(url, token)
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise RuntimeError("GITHUB_API_MISSING_WORKFLOW_RUNS")
    candidates = [
        run for run in runs
        if isinstance(run, dict) and str(run.get("head_branch") or "main") == "main"
    ]
    if not candidates:
        raise RuntimeError("PRODUCTION_RUN_NOT_FOUND")

    def sort_key(run: dict[str, Any]) -> tuple[datetime, int]:
        return (
            _utc(run.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
            int(run.get("id") or 0),
        )

    # The canonical workflow allows one newer run to remain queued behind an
    # older in-progress run. Monitor the active execution first so a queued
    # successor cannot hide a still-running predecessor.
    active = [
        run for run in candidates
        if str(run.get("status") or "").strip().lower() == "in_progress"
    ]
    if active:
        active.sort(key=sort_key, reverse=True)
        return active[0]

    queued = [
        run for run in candidates
        if str(run.get("status") or "").strip().lower()
        in {"queued", "requested", "waiting", "pending"}
    ]
    if queued:
        queued.sort(key=sort_key, reverse=True)
        return queued[0]

    candidates.sort(key=sort_key, reverse=True)
    return candidates[0]


def _current_main_sha(api_base: str, repository: str, token: str) -> str:
    payload = _api_json(f"{api_base}/repos/{repository}/git/ref/heads/main", token)
    obj = payload.get("object")
    if not isinstance(obj, dict) or not obj.get("sha"):
        raise RuntimeError("GITHUB_API_MAIN_SHA_MISSING")
    return str(obj["sha"])


def _run_jobs(api_base: str, repository: str, token: str, run_id: int) -> list[dict[str, Any]]:
    payload = _api_json(
        f"{api_base}/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100",
        token,
    )
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise RuntimeError("GITHUB_API_MISSING_JOBS")
    return [job for job in jobs if isinstance(job, dict)]


def _run_artifacts(api_base: str, repository: str, token: str, run_id: int) -> list[dict[str, Any]]:
    payload = _api_json(
        f"{api_base}/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100",
        token,
    )
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise RuntimeError("GITHUB_API_MISSING_ARTIFACTS")
    return [artifact for artifact in artifacts if isinstance(artifact, dict)]


def build_health(
    *,
    run: dict[str, Any],
    jobs: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    current_main_sha: str,
    now: datetime,
) -> dict[str, Any]:
    run_id = int(run.get("id") or 0)
    if run_id <= 0:
        raise RuntimeError("PRODUCTION_RUN_ID_INVALID")

    run_elapsed = elapsed_minutes(run.get("run_started_at") or run.get("created_at"), now)
    state = classify_run(
        str(run.get("status") or "unknown"),
        str(run.get("conclusion") or ""),
        run_elapsed,
    )
    job_states = {str(job.get("name") or "UNKNOWN"): classify_job(job) for job in jobs}
    active_jobs = sorted(name for name, state_value in job_states.items() if state_value in {"RUNNING", "QUEUED"})
    failed_jobs = sorted(name for name, state_value in job_states.items() if state_value == "FAILURE")

    route_artifact_name = f"production-route-observability-{run_id}"
    route_artifact = next(
        (
            artifact for artifact in artifacts
            if str(artifact.get("name") or "") == route_artifact_name
            and not bool(artifact.get("expired", False))
        ),
        None,
    )

    head_sha = str(run.get("head_sha") or "")
    sha_alignment = bool(head_sha and current_main_sha and head_sha == current_main_sha)
    warnings = []
    if not sha_alignment:
        warnings.append("main_sha_mismatch")
    if failed_jobs:
        warnings.append("failed_job_present")
    if route_artifact is None:
        warnings.append("production_route_artifact_missing")

    return {
        "version": "production-runtime-health-v1",
        "status": "PASS",
        "health_state": state,
        "attention_required": bool(warnings),
        "failure_detected": bool(failed_jobs) or state == "FAILURE",
        "promotion_gate": False,
        "monitoring_only": True,
        "generated_at_utc": now.isoformat(),
        "production_run": {
            "run_id": run_id,
            "workflow": str(run.get("name") or DEFAULT_WORKFLOW),
            "status": str(run.get("status") or "unknown"),
            "conclusion": run.get("conclusion"),
            "head_sha": head_sha or None,
            "current_main_sha": current_main_sha or None,
            "head_sha_matches_current_main": sha_alignment,
            "created_at_utc": run.get("created_at"),
            "run_started_at_utc": run.get("run_started_at"),
            "updated_at_utc": run.get("updated_at"),
            "elapsed_minutes": run_elapsed,
            "html_url": run.get("html_url"),
        },
        "jobs": {
            "total": len(jobs),
            "active": active_jobs,
            "failed": failed_jobs,
            "states": dict(sorted(job_states.items())),
        },
        "artifacts": {
            "production_route_observability_present": route_artifact is not None,
            "production_route_observability_expired": (
                bool(route_artifact.get("expired", False)) if route_artifact else False
            ),
            "artifact_count": len(artifacts),
        },
        "thresholds": {
            "long_running_minutes": LONG_RUNNING_MINUTES,
            "stale_risk_minutes": STALE_RISK_MINUTES,
        },
        "warnings": warnings,
        "interpretation": {
            "stale_risk_is_not_auto_failure": True,
            "health_does_not_promote_or_demote_models": True,
            "head_sha_mismatch_is_operational_warning": not sha_alignment,
        },
    }


def collect(
    *,
    repository: str,
    token: str,
    api_base: str,
    workflow: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    main_sha = _current_main_sha(api_base, repository, token)
    run = _latest_production_run(api_base, repository, token, workflow)
    run_id = int(run.get("id") or 0)
    jobs = _run_jobs(api_base, repository, token, run_id)
    artifacts = _run_artifacts(api_base, repository, token, run_id)
    return build_health(
        run=run,
        jobs=jobs,
        artifacts=artifacts,
        current_main_sha=main_sha,
        now=now,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed health audit for canonical 7-Sport production runtime.")
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    parser.add_argument("--workflow", default=os.environ.get("PRODUCTION_WORKFLOW", DEFAULT_WORKFLOW))
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--api-base", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token or not args.repository:
        raise SystemExit("GITHUB_API_CONTEXT_MISSING")

    try:
        report = collect(
            repository=args.repository,
            token=token,
            api_base=args.api_base.rstrip("/"),
            workflow=args.workflow,
        )
    except Exception as exc:
        error_report = {
            "version": "production-runtime-health-v1",
            "status": "BLOCKED_LOOKUP",
            "health_state": "UNKNOWN",
            "promotion_gate": False,
            "monitoring_only": True,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        }
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(error_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(error_report, ensure_ascii=False, indent=2))
        return 1

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
