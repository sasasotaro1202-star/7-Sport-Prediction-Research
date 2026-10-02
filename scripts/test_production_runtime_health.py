from __future__ import annotations

from datetime import datetime, timezone

from src.production_runtime_health import (
    build_health,
    classify_job,
    classify_run,
)


def main() -> int:
    now = datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc)

    assert classify_run("in_progress", None, 10) == "RUNNING"
    assert classify_run("in_progress", None, 120) == "LONG_RUNNING"
    assert classify_run("in_progress", None, 300) == "STALE_RISK"
    assert classify_run("completed", "success", 10) == "SUCCESS"
    assert classify_run("completed", "failure", 10) == "FAILURE"
    assert classify_run("queued", None, None) == "QUEUED"

    assert classify_job({"status": "in_progress", "conclusion": None}) == "RUNNING"
    assert classify_job({"status": "completed", "conclusion": "success"}) == "SUCCESS"
    assert classify_job({"status": "completed", "conclusion": "failure"}) == "FAILURE"

    from pathlib import Path
    workflow = Path('.github/workflows/production_runtime_health.yml').read_text(encoding='utf-8')
    assert '\\${{' not in workflow
    assert 'name: production-runtime-health-${{ github.run_id }}' in workflow

    from src.production_runtime_health import _latest_production_run

    import src.production_runtime_health as health

    original_api = health._api_json
    payloads = [
        {
            "workflow_runs": [
                {
                    "id": 10,
                    "status": "in_progress",
                    "head_branch": "main",
                    "created_at": "2026-10-01T03:00:00Z",
                },
                {
                    "id": 11,
                    "status": "queued",
                    "head_branch": "main",
                    "created_at": "2026-10-01T04:00:00Z",
                },
            ]
        }
    ]
    health._api_json = lambda *args, **kwargs: payloads[0]
    try:
        selected = _latest_production_run(
            "https://api.github.com",
            "owner/repo",
            "token",
            "v4_5_15_production.yml",
        )
        assert selected["id"] == 10
    finally:
        health._api_json = original_api

    run = {
        "id": 123,
        "name": "Active-Scope Target v4.5.15 Production",
        "status": "in_progress",
        "conclusion": None,
        "head_sha": "abc",
        "created_at": "2026-10-01T03:00:00Z",
        "run_started_at": "2026-10-01T03:00:00Z",
        "updated_at": "2026-10-01T04:55:00Z",
        "html_url": "https://github.com/example/run/123",
    }
    jobs = [
        {"name": "collect / basketball", "status": "completed", "conclusion": "success"},
        {"name": "merge", "status": "in_progress", "conclusion": None},
    ]
    artifacts = [
        {"name": "production-route-observability-123", "expired": False},
    ]
    report = build_health(
        run=run,
        jobs=jobs,
        artifacts=artifacts,
        current_main_sha="abc",
        now=now,
    )

    assert report["status"] == "PASS"
    assert report["health_state"] == "LONG_RUNNING"
    assert report["promotion_gate"] is False
    assert report["attention_required"] is False
    assert report["failure_detected"] is False
    assert report["warnings"] == []
    assert report["production_run"]["head_sha_matches_current_main"] is True
    assert report["jobs"]["active"] == ["merge"]
    assert report["artifacts"]["production_route_observability_present"] is True

    stale_run = dict(run)
    stale_report = build_health(
        run=stale_run,
        jobs=jobs,
        artifacts=[],
        current_main_sha="different",
        now=datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc),
    )
    assert stale_report["health_state"] == "STALE_RISK"
    assert stale_report["production_run"]["head_sha_matches_current_main"] is False
    assert stale_report["artifacts"]["production_route_observability_present"] is False
    assert stale_report["attention_required"] is True
    assert "main_sha_mismatch" in stale_report["warnings"]
    assert "production_route_artifact_missing" in stale_report["warnings"]

    print("PRODUCTION_RUNTIME_HEALTH=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def test_failed_job_sets_failure_signal():
    report = build_health(
        run={
            "id": 12,
            "head_sha": "same",
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-10-01T23:00:00Z",
            "run_started_at": "2026-10-01T23:00:00Z",
        },
        jobs_list=[{"name":"merge","status":"completed","conclusion":"failure"}],
        artifacts_list=[{"name":"production-route-observability-12","expired":False}],
        current_main_sha="same",
        now=datetime(2026,10,2,0,0,tzinfo=timezone.utc),
    )
    assert report["failure_detected"] is True
    assert report["attention_required"] is True
    assert "failed_job_present" in report["warnings"]
