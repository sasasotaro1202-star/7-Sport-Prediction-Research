from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.autonomous_control_plane as cp


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cp.ROOT = root
        cp.RESULTS = root / "results" / "research"
        cp.CONTROL_OUT = cp.RESULTS / "autonomous_control_plane.json"
        cp.HEALTH_OUT = cp.RESULTS / "automation_health.json"
        cp.QUEUE_OUT = cp.RESULTS / "research_queue.jsonl"
        cp.RESULTS.mkdir(parents=True)

        (root / "results").mkdir(exist_ok=True)

        (root / "results/release_gate.json").write_text(json.dumps({
            "status": "READY_WITH_EXPLICIT_DEFERRED_SPORTS",
            "publish": True,
            "coverage": {s: {"accepted_models": 0} for s in cp.ACTIVE_SPORTS},
        }), encoding="utf-8")
        (root / "results/quality_gate.json").write_text(json.dumps({
            "status": "PASS_WITH_PENDING",
            "pending": ["no_exact_pit_replay_rows"],
            "checks": [{"check": "pit_leakage", "exact_pass": 0}],
        }), encoding="utf-8")
        (root / "results/future_predictions.json").write_text(json.dumps({
            "generated_at_utc": "2026-10-03T00:00:00+00:00",
            "sports": [{"sport": s, "status": "NO_FUTURE_EVENTS"} for s in cp.ACTIVE_SPORTS],
        }), encoding="utf-8")
        (root / "results/experience_summary.json").write_text(json.dumps({
            "prediction_archive_total": 0,
            "resolved_scored_total": 0,
            "unresolved_total": 0,
        }), encoding="utf-8")
        (cp.RESULTS / "production_route_observability.json").write_text("{}", encoding="utf-8")
        (cp.RESULTS / "timing_routes.json").write_text("{}", encoding="utf-8")
        (cp.RESULTS / "dual_learning_cycle.json").write_text("{}", encoding="utf-8")
        (root / "results/reproducibility_manifest.json").write_text(json.dumps({
            "source_git_commit_sha": "old-sha",
        }), encoding="utf-8")

        os.environ["GITHUB_SHA"] = "new-sha"
        state = cp.inspect()
        selected, dispatch = cp.choose_actions(state)

        assert selected["action"] == "PIT_COVERAGE_REPAIR", selected
        assert dispatch is not None
        assert dispatch["action"] == "DEEP_RESEARCH", dispatch
        assert selected["automatic_promotion"] is False
        assert dispatch["automatic_promotion"] is False

        first = cp.write_state(state, selected, dispatch)
        assert first["queue_added"] is True
        second = cp.write_state(state, selected, dispatch)
        assert second["queue_added"] is False
        assert cp.QUEUE_OUT.read_text(encoding="utf-8").count("\n") == 1

        control = json.loads(cp.CONTROL_OUT.read_text(encoding="utf-8"))
        assert control["selected_action"]["action"] == "PIT_COVERAGE_REPAIR"
        assert control["dispatch_action"]["action"] == "DEEP_RESEARCH"
        assert control["safety"]["no_model_auto_promotion"] is True

    print("AUTONOMOUS_CONTROL_PLANE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
