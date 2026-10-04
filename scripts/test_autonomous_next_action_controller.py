from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.autonomous_next_action_controller import decide  # noqa: E402


class ControllerContractTests(unittest.TestCase):
    def base(self):
        return {
            "coverage": {
                "basketball": {"accepted_models": 0, "model_safety": "DEFERRED:insufficient_strict_PIT_rows"},
                "volleyball": {"accepted_models": 0, "model_safety": "DEFERRED:insufficient_strict_PIT_rows"},
                "ufc": {"accepted_models": 1, "model_safety": "OK"},
                "rizin": {"accepted_models": 0, "model_safety": "DEFERRED:insufficient_strict_PIT_rows"},
                "valorant": {"accepted_models": 0, "model_safety": "DEFERRED:insufficient_strict_PIT_rows"},
            }
        }

    def test_scope_autofill_for_fresh_coverage_deficit(self):
        d = decide(
            main_sha="abc",
            now=datetime.now(timezone.utc),
            release_gate=self.base(),
            quality_gate={"pending": ["accepted_model_coverage_incomplete"]},
            release_fresh=True,
            quality_fresh=True,
            failures=[],
            workflow_runs={"scope_autofill": [], "autonomous_research_sweep": []},
            force=False,
        )
        self.assertEqual(d["status"], "DISPATCH")
        self.assertEqual(d["action"], "scope_autofill")

    def test_sweep_when_reports_are_stale(self):
        d = decide(
            main_sha="abc",
            now=datetime.now(timezone.utc),
            release_gate=self.base(),
            quality_gate={"pending": ["accepted_model_coverage_incomplete"]},
            release_fresh=False,
            quality_fresh=False,
            failures=[],
            workflow_runs={"scope_autofill": [], "autonomous_research_sweep": []},
            force=False,
        )
        self.assertEqual(d["status"], "DISPATCH")
        self.assertEqual(d["action"], "autonomous_research_sweep")
        self.assertNotIn("accepted_models=0", json.dumps(d))

    def test_hold_after_three_recent_failures(self):
        failures = [
            {"conclusion": "failure", "recorded_at_utc": datetime.now(timezone.utc).isoformat()}
            for _ in range(3)
        ]
        d = decide(
            main_sha="abc",
            now=datetime.now(timezone.utc),
            release_gate=None,
            quality_gate=None,
            release_fresh=False,
            quality_fresh=False,
            failures=failures,
            workflow_runs={"scope_autofill": [], "autonomous_research_sweep": []},
            force=False,
        )
        self.assertEqual(d["status"], "HOLD")
        self.assertIsNone(d["action"])

    def test_bounded_dispatch_when_recent_run_exists(self):
        now = datetime.now(timezone.utc).isoformat()
        d = decide(
            main_sha="abc",
            now=datetime.now(timezone.utc),
            release_gate=self.base(),
            quality_gate={"pending": ["accepted_model_coverage_incomplete"]},
            release_fresh=True,
            quality_fresh=True,
            failures=[],
            workflow_runs={
                "scope_autofill": [{
                    "databaseId": 123,
                    "status": "completed",
                    "conclusion": "success",
                    "headSha": "abc",
                    "createdAt": now,
                    "updatedAt": now,
                }],
                "autonomous_research_sweep": [],
            },
            force=False,
        )
        self.assertEqual(d["status"], "WAIT")
        self.assertIsNone(d["action"])


if __name__ == "__main__":
    unittest.main()
