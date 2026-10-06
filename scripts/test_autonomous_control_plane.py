from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

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


def test_action_health_accepts_successful_durable_only_advance() -> None:
    workflows = {
        "pit_history_expansion.yml": {
            "latest": {
                "databaseId": 101,
                "status": "completed",
                "conclusion": "success",
                "createdAt": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
                "headSha": "old-sha",
                "mainCompatibility": "DURABLE_ONLY",
            }
        }
    }
    health = cp.action_health(
        workflows,
        "pit_history_expansion.yml",
        12.0,
        current_main_sha="current-sha",
    )
    assert health["status"] == "HEALTHY"
    assert health["sha_match"] is False
    assert health["main_compatibility"] == "DURABLE_ONLY"
    assert health["stale"] is False


def test_verified_pit_workflow_suppresses_stale_quality_block() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bind(root)
        fixture(root)
        os.environ["GITHUB_SHA"] = "new-sha"
        snapshot = json.loads(cp.ACTIONS_SNAPSHOT.read_text(encoding="utf-8"))
        snapshot["workflows"]["pit_history_expansion.yml"] = {
            "latest": {
                "databaseId": 102,
                "status": "completed",
                "conclusion": "success",
                "createdAt": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
                "headSha": "new-sha",
                "mainCompatibility": "EXACT_CURRENT_MAIN",
            }
        }
        cp.ACTIONS_SNAPSHOT.write_text(json.dumps(snapshot), encoding="utf-8")
        state = cp.inspect()
        assert state["quality"]["pit_exact_pass"] == 0
        assert state["quality"]["pit_workflow_verified"] is True
        assert state["quality"]["pit_research_blocked"] is False


def test_control_plane_snapshot_records_main_compatibility() -> None:
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "autonomous_control_plane.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "main_compatibility(run_sha)" in text
    assert '"mainCompatibility"' in text
    assert "DURABLE_ONLY" in text


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


def test_action_health_sees_active_older_sha_run() -> None:
    workflows = {
        "autonomous_research_sweep.yml": {
            "latest": {
                "databaseId": 100,
                "status": "completed",
                "conclusion": "success",
                "createdAt": "2099-01-01T00:00:00Z",
                "headSha": "current-sha",
            },
            "recent": [
                {
                    "databaseId": 101,
                    "status": "in_progress",
                    "conclusion": None,
                    "createdAt": "2099-01-01T00:01:00Z",
                    "headSha": "old-sha",
                }
            ],
        }
    }
    health = cp.action_health(
        workflows,
        "autonomous_research_sweep.yml",
        4.5,
        current_main_sha="current-sha",
    )
    assert health["active_run_any"] is True
    assert health["sha_match"] is True


def test_reproducibility_marks_older_manifest_as_stale_snapshot() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        stable = root / "stable-input.txt"
        stable.write_text("stable\n", encoding="utf-8")
        mutable = root / "results/research/autonomous_control_plane.json"
        mutable.parent.mkdir(parents=True)
        mutable.write_text("new-state\n", encoding="utf-8")
        manifest = {
            "source_git_commit_sha": "old-sha",
            "files": [
                {
                    "path": "stable-input.txt",
                    "exists": True,
                    "sha256": cp.sha256_path(stable),
                },
                {
                    "path": "results/research/autonomous_control_plane.json",
                    "exists": True,
                    "sha256": "0" * 64,
                },
            ],
        }
        assessed = cp.assess_reproducibility(manifest, "new-sha", root)
        assert assessed["status"] == "STALE_SNAPSHOT"
        assert assessed["content_match"] is None
        assert assessed["source_sha_match"] is False
        assert assessed["ignored_mutable_files"] == 0
        assert assessed["mismatched_files"] == []
        assert assessed["missing_files"] == []


def test_reproducibility_current_manifest_detects_content_mismatch() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        path = root / "stable-input.txt"
        path.write_text("current\n", encoding="utf-8")
        manifest = {
            "source_git_commit_sha": "current-sha",
            "files": [
                {
                    "path": "stable-input.txt",
                    "exists": True,
                    "sha256": "0" * 64,
                }
            ],
        }
        assessed = cp.assess_reproducibility(manifest, "current-sha", root)
        assert assessed["status"] == "CONTENT_MISMATCH"
        assert assessed["content_match"] is False
        assert assessed["source_sha_match"] is True
        assert assessed["mismatched_files"] == ["stable-input.txt"]

def test_trajectory_control_plane_registration() -> None:
    assert cp.ALLOWED_WORKFLOWS["TRAJECTORY_RESEARCH"] == "autonomous_temporal_trajectory_loop.yml"
    assert cp.MONITORED_WORKFLOWS["trajectory_research"] == "autonomous_temporal_trajectory_loop.yml"


def test_research_sweep_control_plane_registration() -> None:
    assert cp.ALLOWED_WORKFLOWS["RESEARCH_HEALTH"] == "autonomous_research_sweep.yml"
    assert cp.MONITORED_WORKFLOWS["research_sweep"] == "autonomous_research_sweep.yml"


def test_control_plane_concurrency_is_job_scoped_and_coalescing() -> None:
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "autonomous_control_plane.yml"
    text = workflow.read_text(encoding="utf-8")
    before_jobs, after_jobs = text.split("jobs:\n  control:\n", 1)
    assert "\nconcurrency:" not in before_jobs
    concurrency_pos = after_jobs.index("concurrency:")
    group_pos = after_jobs.index("group: autonomous-control-plane-main", concurrency_pos)
    cancel_pos = after_jobs.index("cancel-in-progress: true", group_pos)
    assert concurrency_pos < group_pos < cancel_pos


def test_persist_detects_missing_state_artifacts() -> None:
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "autonomous_control_plane.yml"
    text = workflow.read_text(encoding="utf-8")
    start = text.index("      - name: Persist deterministic control-plane state")
    end = text.index("      - name: Dispatch at most one allowlisted autonomous workflow", start)
    block = text[start:end]
    assert "state_paths=(" in block
    assert 'for state_path in "${state_paths[@]}"; do' in block
    assert 'if [ ! -f "$state_path" ]; then' in block
    assert 'git ls-files --error-unmatch -- "$state_path"' in block
    assert 'CONTROL_PLANE_STATE_NOT_TRACKED path=$state_path' in block
    assert 'if [ "$needs_persist" = false ] && git diff --quiet -- "${state_paths[@]}"; then' in block

def test_pre_event_control_plane_registration() -> None:
    assert cp.ALLOWED_WORKFLOWS["PRODUCTION_HEARTBEAT"] == "pre_event_prediction.yml"
    assert cp.MONITORED_WORKFLOWS["pre_event"] == "pre_event_prediction.yml"

def test_control_plane_workflow_run_triggers_cover_allowlisted_autonomous_workflows() -> None:
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "autonomous_control_plane.yml"
    text = workflow.read_text(encoding="utf-8")
    expected_workflow_names = (
        "Active Source Feasibility Audit",
        "Continuous Scope Autofill and Discovery",
        "Production Runtime Health Audit",
        "Production Safety Audit",
        "Nine-Sport Lane Audit",
        "Autonomous Research Sweep",
        "24H Autonomous Research Marathon",
        "Autonomous Temporal Trajectory Loop",
    )
    for workflow_name in (
        "source_feasibility_audit.yml",
        "scope_autofill.yml",
        "production_runtime_health.yml",
        "production_safety_audit.yml",
        "nine_sport_lane_audit.yml",
        "autonomous_research_sweep.yml",
        "24h_autonomous_research.yml",
        "autonomous_temporal_trajectory_loop.yml",
    ):
        assert workflow_name in text
    for workflow_name in expected_workflow_names:
        assert workflow_name in text

def test_control_plane_has_no_workflow_run_event_injection_path() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "src" / "autonomous_control_plane.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "CONTROL_PLANE_EVENT_WORKFLOW",
        "CONTROL_PLANE_EVENT_CONCLUSION",
        "CONTROL_PLANE_EVENT_HEAD_SHA",
        "CONTROL_PLANE_EVENT_RUN_ID",
        "CONTROL_PLANE_EVENT_ANCESTOR_OF_MAIN",
        "workflow_event_failure:",
        "event_payload_first_failure_triage",
    )
    for token in forbidden:
        assert token not in source, token

def test_pit_recovery_dispatches_only_after_failed_old_sha() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bind(root)
        fixture(root)
        os.environ["GITHUB_SHA"] = "new-sha"
        state = cp.inspect()
        state["actions"]["pit_history"] = {
            "status": "STALE",
            "run_status": "completed",
            "conclusion": "failure",
            "head_sha": "old-sha",
            "current_main_sha": "new-sha",
            "sha_match": False,
            "run_id": 37426080336,
            "active_run_any": False,
            "stale": True,
        }
        state["quality"]["pit_research_blocked"] = True
        selected, dispatch = cp.choose_actions(state)
        assert selected["action"] == "PIT_COVERAGE_REPAIR"
        assert selected["auto_dispatch"] is True
        assert selected["dispatch_policy"] == "bounded_current_main_retry_after_failed_old_sha"
        assert dispatch is not None
        assert dispatch["action"] == "PIT_COVERAGE_REPAIR"
        assert dispatch["workflow"] == "pit_history_expansion.yml"
        assert dispatch["automatic_promotion"] is False

        current = copy.deepcopy(state)
        current["actions"]["pit_history"]["head_sha"] = "new-sha"
        current["actions"]["pit_history"]["sha_match"] = True
        selected_current, dispatch_current = cp.choose_actions(current)
        assert selected_current["action"] == "PIT_COVERAGE_REPAIR"
        assert selected_current["auto_dispatch"] is False
        assert selected_current["dispatch_policy"] == "respect_fixed_pit_boundary_or_existing_watchdog"
        assert dispatch_current is not None
        assert dispatch_current["workflow"] != "pit_history_expansion.yml"


def test_pit_recovery_refreshes_after_meaningful_main_change() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bind(root)
        fixture(root)
        os.environ["GITHUB_SHA"] = "new-sha"
        state = cp.inspect()
        state["actions"]["pit_history"] = {
            "status": "STALE",
            "run_status": "completed",
            "conclusion": "success",
            "head_sha": "old-sha",
            "current_main_sha": "new-sha",
            "sha_match": False,
            "main_compatibility": "MEANINGFUL_OR_DIVERGED",
            "run_id": 37440505534,
            "active_run_any": False,
            "stale": True,
        }
        state["quality"]["pit_research_blocked"] = True
        selected, dispatch = cp.choose_actions(state)
        assert selected["action"] == "PIT_COVERAGE_REPAIR"
        assert selected["auto_dispatch"] is True
        assert selected["dispatch_policy"] == "bounded_current_main_refresh_after_meaningful_change"
        assert dispatch is not None
        assert dispatch["workflow"] == "pit_history_expansion.yml"
        assert dispatch["automatic_promotion"] is False


def test_control_plane_dispatch_has_live_all_sha_guard() -> None:
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "autonomous_control_plane.yml"
    text = workflow.read_text(encoding="utf-8")
    start = text.index("      - name: Dispatch at most one allowlisted autonomous workflow")
    end = text.index("      - name: Final control-plane status", start)
    block = text[start:end]
    assert 'gh run list --workflow "$DISPATCH_WORKFLOW" --limit 100' in block
    assert "active_any=" in block
    assert '[.[] | select(.status=="queued" or .status=="in_progress"' in block
    assert 'if [ "$active_any" -eq 0 ]; then' in block



def test_control_plane_has_bounded_pit_recovery_gate() -> None:
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "autonomous_control_plane.yml"
    text = workflow.read_text(encoding="utf-8")
    start = text.index("      - name: Validate current B.LEAGUE PIT bridge before recovery dispatch")
    end = text.index("      - name: Inspect current GitHub evidence", start)
    assert "scripts/test_bleague_exact_pit_bridge.py" in text[start:end]
    dispatch_start = text.index("      - name: Dispatch at most one allowlisted autonomous workflow")
    dispatch_end = text.index("      - name: Final control-plane status", dispatch_start)
    block = text[dispatch_start:dispatch_end]
    assert "pit_history_expansion.yml)" in block
    assert "cooldown=21600" in block


def test_control_plane_dispatch_verifies_run_creation() -> None:
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "autonomous_control_plane.yml"
    text = workflow.read_text(encoding="utf-8")
    start = text.index("      - name: Dispatch at most one allowlisted autonomous workflow")
    end = text.index("      - name: Final control-plane status", start)
    block = text[start:end]
    assert 'dispatch_started_at="$(date -u +%s)"' in block
    assert "AUTO_DISPATCH_VERIFIED" in block
    assert "AUTO_DISPATCH_UNVERIFIED" in block
    assert "fromdateiso8601" in block


def test_research_queue_identity_excludes_volatile_fields() -> None:
    a = {
        "action": "PIT_COVERAGE_REPAIR",
        "workflow": "pit_history_expansion.yml",
        "target": "active_scope",
        "reason": "reason-a",
        "dispatch_policy": "policy-a",
        "priority": 100,
        "head_sha": "sha-a",
    }
    b = dict(a, reason="reason-b", dispatch_policy="policy-b", priority=1, head_sha="sha-b")
    assert cp.queue_identity(a) == cp.queue_identity(b)


def test_research_queue_compaction_keeps_latest_logical_task() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bind(root)
        root.joinpath("results/research").mkdir(parents=True)
        rows = []
        for sha in ("old-sha", "new-sha"):
            rows.append({
                "action": "PIT_COVERAGE_REPAIR",
                "workflow": "pit_history_expansion.yml",
                "target": "active_scope",
                "reason": "same logical task",
                "dispatch_policy": "respect_fixed_pit_boundary_or_existing_watchdog",
                "head_sha": sha,
                "queue_key": "legacy-obsolete-key",
            })
        cp.QUEUE_OUT.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        before, after = cp.compact_research_queue()
        assert (before, after) == (2, 1)
        compacted = [
            json.loads(line)
            for line in cp.QUEUE_OUT.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(compacted) == 1
        assert compacted[0]["head_sha"] == "new-sha"
        assert compacted[0]["queue_key"] == cp.queue_identity(compacted[0])
        assert compacted[0]["queue_key"] != "legacy-obsolete-key"


def main() -> int:
    test_action_health_rejects_missing_sha_provenance()
    test_action_health_rejects_old_sha()
    test_action_health_accepts_successful_durable_only_advance()
    test_verified_pit_workflow_suppresses_stale_quality_block()
    test_control_plane_snapshot_records_main_compatibility()
    test_reproducibility_marks_older_manifest_as_stale_snapshot()
    test_reproducibility_current_manifest_detects_content_mismatch()
    # The current-manifest mismatch case is covered by the explicit current-SHA test above.
    test_trajectory_control_plane_registration()
    test_research_sweep_control_plane_registration()
    test_pre_event_control_plane_registration()
    test_control_plane_concurrency_is_job_scoped_and_coalescing()
    test_pit_recovery_dispatches_only_after_failed_old_sha()
    test_pit_recovery_refreshes_after_meaningful_main_change()
    test_control_plane_has_bounded_pit_recovery_gate()
    test_control_plane_dispatch_verifies_run_creation()
    test_control_plane_has_no_workflow_run_event_injection_path()
    test_research_queue_identity_excludes_volatile_fields()
    test_research_queue_compaction_keeps_latest_logical_task()
    test_persist_detects_missing_state_artifacts()
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
        assert selected["action"] == "PIT_COVERAGE_REPAIR", selected
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
        # These fields are derived from the control-plane invocation SHA and
        # current wall-clock time, not from a new workflow run.
        same_evidence_new_sha["actions"]["runtime_health"]["current_main_sha"] = "next-sha"
        same_evidence_new_sha["actions"]["runtime_health"]["sha_match"] = False
        same_evidence_new_sha["actions"]["runtime_health"]["stale"] = True
        same_evidence_new_sha["actions"]["runtime_health"]["status"] = "STALE"
        selected_next, dispatch_next = cp.choose_actions(same_evidence_new_sha)
        second = cp.write_state(same_evidence_new_sha, selected_next, dispatch_next)

        assert first["queue_added"] is True
        assert second["queue_added"] is False
        assert first["state_fingerprint"] == second["state_fingerprint"]
        assert first["write_needed"] is True
        assert second["write_needed"] is False
        assert cp.ACTION_LOG_OUT.read_text(encoding="utf-8").count("\n") == 1

        # A changed workflow run id alone is attempt metadata and must not
        # change the durable control-state fingerprint or append a queue item.
        same_evidence_run_id = copy.deepcopy(same_evidence_new_sha)
        same_evidence_run_id["actions"]["runtime_health"]["run_id"] = 123456789
        selected_run_id, dispatch_run_id = cp.choose_actions(same_evidence_run_id)
        third = cp.write_state(same_evidence_run_id, selected_run_id, dispatch_run_id)
        assert third["state_fingerprint"] == second["state_fingerprint"]
        assert third["queue_added"] is False
        assert cp.QUEUE_OUT.read_text(encoding="utf-8").count("\n") == 1
        assert cp.ACTION_LOG_OUT.read_text(encoding="utf-8").count("\n") == 1

        # A genuinely changed workflow result changes the state fingerprint,
        # but still must not duplicate the same unresolved logical task.
        changed_evidence = copy.deepcopy(same_evidence_run_id)
        changed_evidence["actions"]["runtime_health"]["conclusion"] = "failure"
        selected_changed, dispatch_changed = cp.choose_actions(changed_evidence)
        fourth = cp.write_state(changed_evidence, selected_changed, dispatch_changed)
        assert fourth["state_fingerprint"] != third["state_fingerprint"]
        assert fourth["queue_added"] is False
        assert cp.QUEUE_OUT.read_text(encoding="utf-8").count("\n") == 1
        assert cp.ACTION_LOG_OUT.read_text(encoding="utf-8").count("\n") == 2

        # A genuinely different logical task must enqueue a new transition.
        new_task = copy.deepcopy(selected_changed)
        new_task["target"] = "different_target"
        fifth = cp.write_state(changed_evidence, new_task, dispatch_changed)
        assert fifth["queue_added"] is True
        queue_rows = [
            json.loads(line)
            for line in cp.QUEUE_OUT.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(queue_rows) == 2
        assert queue_rows[-1]["queue_key"] != queue_rows[0]["queue_key"]

        control = json.loads(cp.CONTROL_OUT.read_text(encoding="utf-8"))
        assert control["automatic_promotion"] is False
        assert control["safety"]["automatic_dispatch_is_bounded_and_allowlisted"] is True

        # Missing evidence must never become a zero-valued performance claim.
        (root / "results/release_gate.json").write_text(
            json.dumps({"status": "UNKNOWN", "coverage": {}}), encoding="utf-8"
        )
        missing = cp.inspect()
        assert missing["release"]["active_accepted_model_gap"] == []
        assert missing["errors"]["release_gate.coverage.valorant"] == "MISSING_OR_INVALID"

        # Recent observed failures must become an autonomous research signal.
        selected_failure, dispatch_failure = cp.choose_actions(state)
        assert selected_failure["action"] == "PIT_COVERAGE_REPAIR"
        assert selected_failure["target"] == "active_scope"
        assert dispatch_failure is not None
        assert dispatch_failure["workflow"] == "autonomous_research_sweep.yml"

    print("AUTONOMOUS_CONTROL_PLANE_V2=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Regression fixture: the stale-event case must clear ancestor provenance before inspection.
