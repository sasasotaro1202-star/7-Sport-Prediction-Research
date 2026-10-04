from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
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
            "recorded_at_utc": "2026-10-04T04:00:00+00:00",
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
            "latest": {"databaseId": 4, "status": "completed", "conclusion": "success", "createdAt": "2026-10-04T00:00:00Z", "headSha": "new-sha"},
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
            "latest": {"databaseId": 8, "status": "completed", "conclusion": "success", "createdAt": "2026-10-04T08:00:00Z", "headSha": "new-sha"},
        },
    }
    cp.ACTIONS_SNAPSHOT.write_text(json.dumps({"workflows": workflows, "errors": {}}), encoding="utf-8")


def main() -> int:
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
        same_evidence_new_sha = copy.deepcopy(state)
        same_evidence_new_sha["head_sha"] = "next-sha"
        original_runtime_age = same_evidence_new_sha["actions"]["runtime_health"]["age_hours"]
        same_evidence_new_sha["actions"]["runtime_health"]["age_hours"] = (
            original_runtime_age + 0.1 if original_runtime_age is not None else 0.1
        )
        selected_next, dispatch_next = cp.choose_actions(same_evidence_new_sha)
        second = cp.write_state(same_evidence_new_sha, selected_next, dispatch_next)

        assert first["queue_added"] is True
        assert second["queue_added"] is False
        assert first["state_fingerprint"] == second["state_fingerprint"]
        assert first["write_needed"] is True
        assert second["write_needed"] is False
        assert cp.ACTION_LOG_OUT.read_text(encoding="utf-8").count("\n") == 1

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

    print("AUTONOMOUS_CONTROL_PLANE_V2=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
