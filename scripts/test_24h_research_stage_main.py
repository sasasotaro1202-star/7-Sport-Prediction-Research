from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


class StageEvidencePolicyTests(unittest.TestCase):
    def test_explicit_nontrained_status_is_degraded_not_critical(self):
        from scripts import run_24h_research_stage_main as runner

        for status in (
            "DEFERRED",
            "DEFERRED_PIT",
            "DEFERRED_RETRAIN_CARRY_FORWARD",
            "DEFERRED_FROZEN_HOLDOUT",
            "DEFERRED_MATCHDAY_CONTEXT",
            "REJECTED_FROZEN_HOLDOUT",
            "REJECTED_HOLDOUT_CALIBRATION",
            "REJECTED_CHALLENGER",
            "INSUFFICIENT_OOS",
        ):
            result = runner.classify_primary_evidence(
                "basketball",
                {"sport": "basketball", "status": status},
                expected_sha="new-sha",
            )
            self.assertEqual(result["classification"], "DEGRADED_EXPLICIT_STATUS")
            self.assertFalse(result["critical"])

    def test_failed_or_unknown_status_is_critical(self):
        from scripts import run_24h_research_stage_main as runner

        for status in ("FAILED", "UNKNOWN", "NOT_A_REAL_STATUS"):
            result = runner.classify_primary_evidence(
                "basketball",
                {"sport": "basketball", "status": status},
                expected_sha="new-sha",
            )
            self.assertEqual(result["classification"], "CRITICAL")
            self.assertTrue(result["critical"])

    def test_missing_primary_evidence_is_degraded_only_until_next_cycle(self):
        from scripts import run_24h_research_stage_main as runner

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = runner.classify_primary_evidence_from_path(
                "basketball",
                root / "basketball.json",
                expected_sha="new-sha",
            )
        self.assertEqual(result["classification"], "DEGRADED_MISSING_OR_INVALID")
        self.assertFalse(result["critical"])

    def test_trained_status_requires_fresh_sha(self):
        from scripts import run_24h_research_stage_main as runner

        fresh = runner.classify_primary_evidence(
            "basketball",
            {"sport": "basketball", "status": "TRAINED", "git_commit_sha": "new-sha"},
            expected_sha="new-sha",
        )
        stale = runner.classify_primary_evidence(
            "basketball",
            {"sport": "basketball", "status": "TRAINED", "git_commit_sha": "old-sha"},
            expected_sha="new-sha",
        )
        self.assertEqual(fresh["classification"], "TRAINED_FRESH")
        self.assertEqual(stale["classification"], "CRITICAL_STALE_TRAINED")


class FinalReconciliationBehaviorTests(unittest.TestCase):
    def _write(self, root: Path, stage: int, sport: str, status: str = "PASS") -> None:
        payload = {
            "stage": stage,
            "sport": sport,
            "status": status,
            "github_sha": "sha",
            "iterations": 1,
            "command_count": 2,
            "critical_failures": [] if status != "FAILED" else ["stage_failure"],
            "degraded_tasks": [] if status == "PASS" else ["evidence_degraded"],
        }
        path = root / f"stage_{stage}_final.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_all_five_pass_reconciles_to_pass(self):
        from scripts import reconcile_24h_research as reconcile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for stage, sport in reconcile.EXPECTED_STAGES.items():
                self._write(root, stage, sport)
            with patch.object(reconcile, "current_remote_sha", return_value="sha"), patch.dict(
                __import__("os").environ, {"GITHUB_SHA": "sha"}, clear=False
            ):
                out = reconcile.reconcile(root)
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(out["failed_stages"], [])
        self.assertEqual(out["degraded_stages"], [])

    def test_one_degraded_stage_is_explicitly_degraded(self):
        from scripts import reconcile_24h_research as reconcile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for stage, sport in reconcile.EXPECTED_STAGES.items():
                self._write(root, stage, sport, "DEGRADED" if stage == 2 else "PASS")
            with patch.object(reconcile, "current_remote_sha", return_value="sha"), patch.dict(
                __import__("os").environ, {"GITHUB_SHA": "sha"}, clear=False
            ):
                out = reconcile.reconcile(root)
        self.assertEqual(out["status"], "DEGRADED")
        self.assertEqual(out["degraded_stages"], [2])

    def test_missing_stage_is_failed_closed(self):
        from scripts import reconcile_24h_research as reconcile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for stage, sport in reconcile.EXPECTED_STAGES.items():
                if stage != 5:
                    self._write(root, stage, sport)
            with patch.object(reconcile, "current_remote_sha", return_value="sha"), patch.dict(
                __import__("os").environ, {"GITHUB_SHA": "sha"}, clear=False
            ):
                out = reconcile.reconcile(root)
        self.assertEqual(out["status"], "FAILED")
        self.assertEqual(out["missing_stages"], [5])




class WorkflowFinalReconciliationContractTests(unittest.TestCase):
    def test_final_reconciliation_script_and_download_contract_exist(self):
        workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "24h_autonomous_research.yml"
        text = workflow.read_text(encoding="utf-8")
        self.assertIn("actions/download-artifact@v7", text)
        self.assertIn('name: "Download all 24H stage evidence"', text)
        self.assertIn("python scripts/reconcile_24h_research.py", text)
        script = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_24h_research.py"
        self.assertTrue(script.is_file())

    def test_workflow_contract_checks_actual_reconciliation_script(self):
        workflow_test = Path(__file__).resolve().parents[0] / "test_24h_workflow_contract.py"
        text = workflow_test.read_text(encoding="utf-8")
        self.assertNotIn('rglob("stage_*_final.json")', text)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
