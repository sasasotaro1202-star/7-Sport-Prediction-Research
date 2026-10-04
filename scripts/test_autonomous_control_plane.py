from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.autonomous_control_plane as cp


def bind(root: Path) -> None:
    cp.ROOT = root
    cp.RESULTS = root / "results" / "research"
    cp.CONTROL_OUT = cp.RESULTS / "autonomous_control_plane.json"
    cp.HEALTH_OUT = cp.RESULTS / "automation_health.json"
    cp.QUEUE_OUT = cp.RESULTS / "research_queue.jsonl"
    cp.ACTION_LOG_OUT = cp.RESULTS / "autonomous_action_log.jsonl"
    cp.ACTIONS_SNAPSHOT = root / "results" / "automation_state" / "actions_snapshot.json"


def fixture(root: Path) -> None:
    recent_utc = datetime.now(timezone.utc) - timedelta(minutes=10)
    recent_iso = recent_utc.isoformat().replace("+00:00", "Z")
    (root / "results").mkdir(parents=True, exist_ok=True)
    (root / "results/research").mkdir(parents=True, exist_ok=True)
    (root / "results/automation_state").mkdir(parents=True, exist_ok=True)

    coverage = {sport: {"accepted_models": 0} for sport in cp.ACTIVE_SPORTS}
    (root / "results/release_gate.json").write_text(
        json.dumps({"status": "READY_WITH_EXPLICIT_DEFERRED_SPORTS", "publish": True, "coverage": coverage}),
        encoding="utf-8",
    )
    (root / "results/quality_gate.json").write_text(
        json.dumps({
            "status": "PASS_WITH_PENDING",
            "pending": ["no_exact_pit_replay_rows"],
            "checks": [{"check": "pit_leakage", "exact_pass": 0}],
        }),
        encoding="utf-8",
    )
    (root / "results/future_predictions.json").write_text(
        json.dumps({
            "generated_at_utc": "2026-10-03T00:00:00+00:00",
            "sports": [{"sport": s, "status": "NO_FUTURE_EVENTS"} for s in cp.ACTIVE_SPORTS],
        }),
        encoding="utf-8",
    )
    (root / "results/experience_summary.json").write_text(
        json.dumps({
            "generated_at_utc": "2026-10-03T00:00:00+00:00",
            "prediction_archive_total": 0,
            "resolved_scored_total": 0,
            "unresolved_total": 0,
        }),
        encoding="utf-8",
    )
    (root / "results/research/production_route_observability.json").write_text(
        json.dumps({
            "source": {"prediction_rows": 0},
            "route_registry": {"accepted_route_count": 0},
            "timing_registry": {"accepted_route_count": 0},
        }),
        encoding="utf-8",
    )
    (root / "results/research/timing_routes.json").write_text(
        json.dumps({"status": "READY_NO_ACCEPTED_ROUTES", "routes": {}}),
        encoding="utf-8",
    )
    (root / "results/research/dual_learning_cycle.json").write_text(
        json.dumps({"status": "SUCCESS", "finished_at_utc": "2026-10-03T00:00:00+00:00"}),
        encoding="utf-8",
    )
    (root / "results/reproducibility_manifest.json").write_text(
        json.dumps({"source_git_commit_sha": "old-sha"}),
        encoding="utf-8",
    )

    (root / "results/failure_memory.jsonl").write_text(
        json.dumps({
            "record_id": "run-test",
            "recorded_at_utc": recent_iso,
            "failure_class": "COLLECTION_WORKFLOW_FAILURE",
            "unknown_details_are_not_inferred": True,
        }) + "\n",
        encoding="utf-8",
    )

    workflows = {
        "source_feasibility_audit.yml": {
            "latest": {"databaseId": 1, "status": "completed", "conclusion": "failure", "createdAt": "2026-10-04T00:00:00Z", "headSha": "new-sha"},
        },
        "scope_autofill.yml": {
            "latest": {"databaseId": 2, "status": "completed", "conclusion": "success", "createdAt": "2026-10-04T03:30:00Z", "headSha": "new-sha"},
        },
        "production_runtime_health.yml": {
            "latest": {"databaseId": 3, "status": "completed", "conclusion": "success", "createdAt": "2026-10-04T00:10:00Z", "headSha": "new-sha"},
        },
        "production_safety_audit.yml": {
            "latest": {"databaseId": 4, "status": "completed", "conclusion": "success", "createdAt": "2026-10-04T00:00:00Z", "headSha": "old-sha"},
        },
        "nine_sport_lane_audit.yml": {
            "latest": {"databaseId": 5, "status": "completed", "conclusion": "success", "createdAt": "2026-10-04T00:00:00Z", "headSha": "new-sha"},
        },
        "autonomous_research_sweep.yml": {
            "latest": {"databaseId": 6, "status": "completed", "conclusion": "success", "createdAt": "2026-10-04T00:00:00Z", "headSha": "new-sha"},
        },
        "24h_autonomous_research.yml": {
            "latest": {"databaseId": 7, "status": "completed", "conclusion": "success", "createdAt": "2026-10-03T00:00:00Z", "headSha": "new-sha"},
        },
        "pre_event_prediction.yml": {
            "latest": {"databaseId": 8, "status": "completed", "conclusion": "success", "createdAt": recent_iso, "headSha": "new-sha"},
        },
    }
    cp.ACTIONS_SNAPSHOT.write_text(json.dumps({"workflows": workflows, "errors": {}}), encoding="utf-8")


def test_action_health_rejects_missing_sha_provenance() -> None:
    workflows = {
        "production_safety_audit.yml": {
            "latest": {
                "databaseId": 100,
                "status": "completed",
                "conclusion": "success",
                "createdAt": "2099-01-01T00:00:00Z",
            }
        }
    }
    health = cp.action_health(
        workflows,
        "production_safety_audit.yml",
        4.5,
        current_main_sha="current-sha",
    )
    assert health["status"] == "STALE"
    assert health["stale"] is True
    assert health["sha_match"] is None


def test_action_health_rejects_old_sha() -> None:
    workflows = {
        "production_safety_audit.yml": {
            "latest": {
                "databaseId": 99,
                "status": "completed",
                "conclusion": "success",
                "createdAt": "2099-01-01T00:00:00Z",
                "headSha": "old-sha",
            }
        }
    }
    health = cp.action_health(workflows, "production_safety_audit.yml", 4.5, current_main_sha="current-sha")
    assert health["status"] == "STALE"
    assert health["stale"] is True


def main() -> int:
    test_action_health_rejects_missing_sha_provenance()
    test_action_health_rejects_old_sha()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bind(root)
        fixture(root)
        os.environ["GITHUB_SHA"] = "new-sha"

        state = cp.inspect()
        assert state["actions"]["source_feasibility"]["status"] == "FAILED"
        assert state["failure_memory"]["records_total"] == 1
        assert state["failure_memory"]["recent_24h"] == 1
        assert state["actions"]["pre_event_prediction"]["status"] == "HEALTHY"
        assert state["actions"]["safety_audit"]["status"] == "STALE"
        assert state["actions"]["safety_audit"]["sha_match"] is False
        selected, dispatch = cp.choose_actions(state)
        assert selected["action"] == "RUNTIME_HEALTH" or selected["action"] == "DEEP_RESEARCH", selected
        assert dispatch is not None
        assert dispatch["workflow"] in {
            "production_runtime_health.yml",
            "24h_autonomous_research.yml",
            "autonomous_research_sweep.yml",
            "source_feasibility_audit.yml",
            "scope_autofill.yml",
            "production_safety_audit.yml",
            "nine_sport_lane_audit.yml",
        }
        assert dispatch["automatic_promotion"] is False

        first = cp.write_state(state, selected, dispatch)
        second = cp.write_state(state, selected, dispatch)
        assert first["queue_added"] is True
        assert second["queue_added"] is False
        assert cp.ACTION_LOG_OUT.read_text(encoding="utf-8").count("\n") == 2

        control = json.loads(cp.CONTROL_OUT.read_text(encoding="utf-8"))
        assert control["automatic_promotion"] is False
        assert control["safety"]["automatic_dispatch_is_bounded_and_allowlisted"] is True

        # Missing evidence must never become a zero-valued performance claim.
        (root / "results/release_gate.json").write_text(
            json.dumps({"status": "UNKNOWN", "coverage": {}}), encoding="utf-8"
        )
        missing = cp.inspect()
        assert missing["release"]["active_accepted_model_gap"] == []
        assert "release_gate.coverage.valorant.accepted_models" in missing["errors"]

        # Recent observed failures must become an autonomous research signal.
        selected_failure, dispatch_failure = cp.choose_actions(state)
        assert selected_failure["target"] == "recent_failures"
        assert dispatch_failure is not None
        assert dispatch_failure["workflow"] == "autonomous_research_sweep.yml"

        # The triggering workflow_run failure remains actionable even when the
        # latest snapshot has already moved to a newer successful run.
        (root / "results/failure_memory.jsonl").unlink()
        workflows = json.loads(cp.ACTIONS_SNAPSHOT.read_text(encoding="utf-8"))
        workflows["workflows"]["v4_5_15_production.yml"] = {
            "latest": {
                "databaseId": 99,
                "status": "completed",
                "conclusion": "success",
                "createdAt": recent_iso,
                "headSha": "new-sha",
            }
        }
        cp.ACTIONS_SNAPSHOT.write_text(json.dumps(workflows), encoding="utf-8")
        os.environ["CONTROL_PLANE_EVENT_WORKFLOW"] = "v4_5_15_production.yml"
        os.environ["CONTROL_PLANE_EVENT_CONCLUSION"] = "failure"
        os.environ["CONTROL_PLANE_EVENT_HEAD_SHA"] = "new-sha"
        event_state = cp.inspect()
        _, event_dispatch = cp.choose_actions(event_state)
        assert event_dispatch is not None
        assert event_dispatch["target"] == "workflow_event_failure:production"
        assert event_dispatch["workflow"] == "autonomous_research_sweep.yml"

        # A stale event SHA is fail-closed and must not create this event signal.
        os.environ["CONTROL_PLANE_EVENT_HEAD_SHA"] = "stale-sha"
        stale_state = cp.inspect()
        _, stale_dispatch = cp.choose_actions(stale_state)
        assert stale_dispatch is None or stale_dispatch["target"] != "workflow_event_failure:production"

    print("AUTONOMOUS_CONTROL_PLANE_V2=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
