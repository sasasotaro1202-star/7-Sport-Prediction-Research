from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WorkflowContractTests(unittest.TestCase):
    def test_active_scope_excludes_baseball_and_soccer(self):
        cfg = json.loads((ROOT / "config" / "ACTIVE_SCOPE_9_SPORTS.json").read_text(encoding="utf-8"))
        active = cfg.get("active_scope", {})
        self.assertNotIn("baseball", active)
        self.assertNotIn("soccer", active)
        self.assertEqual(
            set(active),
            {"basketball", "volleyball", "ufc", "rizin", "valorant"},
        )

    def test_24h_workflow_is_not_per_commit(self):
        text = (ROOT / ".github" / "workflows" / "24h_autonomous_research.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("\n  push:\n", text)
        self.assertIn("\n  schedule:\n", text)
        self.assertIn("\n  workflow_dispatch:\n", text)

    def test_all_stage_checkpoints_are_success_only(self):
        text = (ROOT / ".github" / "workflows" / "24h_autonomous_research.yml").read_text(
            encoding="utf-8"
        )
        for sport in ("basketball", "volleyball", "ufc", "rizin", "valorant"):
            pattern = (
                rf'- name: Save {sport} DB checkpoint\n'
                rf'        if: success\(\)'
            )
            self.assertRegex(text, pattern)

    def test_final_reconciliation_exists(self):
        text = (ROOT / ".github" / "workflows" / "24h_autonomous_research.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('name: "Final / 24H evidence reconciliation"', text)
        self.assertIn('rglob("stage_*_final.json")', text)

    def test_watchdog_waits_when_no_verified_current_cycle_exists(self):
        text = (ROOT / ".github" / "workflows" / "24h_autonomous_research_watchdog.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('reason": "await_scheduled_cycle_for_current_main"', text)
        self.assertNotIn('reason": "no_verified_run_for_current_main"', text)

    def test_runner_uses_stage_sport_and_bounded_cycle(self):
        text = (ROOT / "scripts" / "run_24h_research_stage_main.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '["python", "-m", "src.pit_replay_builder", "--sport", sport]',
            text,
        )
        self.assertIn("cycle_interval_minutes", text)
        self.assertIn("MIN_CYCLE_INTERVAL_MINUTES = 5", text)
        self.assertNotIn("last_research", text)
        self.assertIn("next_cycle_at", text)

    def test_watchdog_binds_to_latest_main(self):
        text = (ROOT / ".github" / "workflows" / "24h_autonomous_research_watchdog.yml").read_text(
            encoding="utf-8"
        )
        for token in ("MAIN_SHA=", "headSha", "latest_current_main_run_failed", "dispatch verified"):
            self.assertIn(token, text)

    def test_runner_has_fresh_evidence_gate(self):
        text = (ROOT / "scripts" / "run_24h_research_stage_main.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("verify_24h_research_evidence.py", text)
        self.assertIn('HARD_EXCLUDED = {"baseball", "soccer"}', text)


if __name__ == "__main__":
    unittest.main()
