from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.autonomous_control_plane as cp


def write_fixture(root: Path, *, include_exact_pit: bool = True, include_model_counts: bool = True) -> None:
    (root / "results").mkdir(parents=True, exist_ok=True)
    (root / "results/research").mkdir(parents=True, exist_ok=True)

    coverage = {}
    for sport in cp.ACTIVE_SPORTS:
        coverage[sport] = {"accepted_models": 0} if include_model_counts else {}
    (root / "results/release_gate.json").write_text(json.dumps({
        "status": "READY_WITH_EXPLICIT_DEFERRED_SPORTS",
        "publish": True,
        "coverage": coverage,
    }), encoding="utf-8")

    checks = []
    if include_exact_pit:
        checks = [{"check": "pit_leakage", "exact_pass": 0}]
    (root / "results/quality_gate.json").write_text(json.dumps({
        "status": "PASS_WITH_PENDING",
        "pending": ["no_exact_pit_replay_rows"] if include_exact_pit else [],
        "checks": checks,
    }), encoding="utf-8")

    (root / "results/future_predictions.json").write_text(json.dumps({
        "generated_at_utc": "2026-10-03T00:00:00+00:00",
        "sports": [{"sport": s, "status": "NO_FUTURE_EVENTS"} for s in cp.ACTIVE_SPORTS],
    }), encoding="utf-8")
    (root / "results/experience_summary.json").write_text(json.dumps({
        "generated_at_utc": "2026-10-03T00:00:00+00:00",
        "prediction_archive_total": 0,
        "resolved_scored_total": 0,
        "unresolved_total": 0,
    }), encoding="utf-8")
    (root / "results/research/production_route_observability.json").write_text(json.dumps({
        "source": {"prediction_rows": 0},
        "route_registry": {"accepted_route_count": 0},
        "timing_registry": {"accepted_route_count": 0},
    }), encoding="utf-8")
    (root / "results/research/timing_routes.json").write_text(json.dumps({
        "status": "READY_NO_ACCEPTED_ROUTES",
        "routes": {},
    }), encoding="utf-8")
    (root / "results/research/dual_learning_cycle.json").write_text(json.dumps({
        "status": "SUCCESS",
        "finished_at_utc": "2026-10-03T00:00:00+00:00",
    }), encoding="utf-8")
    (root / "results/reproducibility_manifest.json").write_text(json.dumps({
        "source_git_commit_sha": "old-sha",
    }), encoding="utf-8")


def bind_paths(root: Path) -> None:
    cp.ROOT = root
    cp.RESULTS = root / "results" / "research"
    cp.CONTROL_OUT = cp.RESULTS / "autonomous_control_plane.json"
    cp.HEALTH_OUT = cp.RESULTS / "automation_health.json"
    cp.QUEUE_OUT = cp.RESULTS / "research_queue.jsonl"


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bind_paths(root)
        write_fixture(root)

        os.environ["GITHUB_SHA"] = "new-sha"
        state = cp.inspect()
        selected, dispatch = cp.choose_actions(state)

        assert selected["action"] == "PIT_COVERAGE_REPAIR", selected
        assert dispatch is not None and dispatch["action"] == "DEEP_RESEARCH", dispatch
        assert state["reproducibility"]["status"] == "STALE_OR_MISSING"
        assert selected["automatic_promotion"] is False

        first = cp.write_state(state, selected, dispatch)
        assert first["queue_added"] is True
        second = cp.write_state(state, selected, dispatch)
        assert second["queue_added"] is False
        assert cp.QUEUE_OUT.read_text(encoding="utf-8").count("\n") == 1

        control = json.loads(cp.CONTROL_OUT.read_text(encoding="utf-8"))
        assert control["safety"]["missing_not_zero"] is True
        assert control["automatic_promotion"] is False

        # Missing accepted_models must not silently become an explicit zero/model gap.
        root2 = Path(td) / "missing-evidence"
        bind_paths(root2)
        write_fixture(root2, include_exact_pit=False, include_model_counts=False)
        os.environ["GITHUB_SHA"] = "new-sha"
        missing_state = cp.inspect()
        assert missing_state["release"]["active_accepted_model_gap"] == []
        assert "release_gate.coverage.valorant.accepted_models" in missing_state["errors"]
        missing_selected, missing_dispatch = cp.choose_actions(missing_state)
        assert missing_selected["action"] == "PIT_COVERAGE_REPAIR"
        assert missing_dispatch is not None and missing_dispatch["action"] == "RESEARCH_HEALTH"

        # Age changes must not create a new state fingerprint when source evidence is unchanged.
        fixed = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
        cp.now_utc = lambda: fixed
        bind_paths(Path(td) / "stable")
        write_fixture(cp.ROOT)
        a = cp.inspect()
        sa, da = cp.choose_actions(a)
        fpa = cp.state_fingerprint(a, sa, da)
        cp.now_utc = lambda: fixed.replace(hour=13)
        b = cp.inspect()
        sb, db = cp.choose_actions(b)
        fpb = cp.state_fingerprint(b, sb, db)
        assert a["future_prediction"]["age_class"] == b["future_prediction"]["age_class"] == "STALE"
        assert fpa == fpb

    print("AUTONOMOUS_CONTROL_PLANE_HARDENING=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
