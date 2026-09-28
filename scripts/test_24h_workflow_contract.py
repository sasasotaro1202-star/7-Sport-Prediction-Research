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

    def test_24h_workflow_does_not_self_trigger_on_workflow_edits(self):
        text = (ROOT / ".github" / "workflows" / "24h_autonomous_research.yml").read_text(
            encoding="utf-8"
        )
        push = re.search(r"(?ms)^  push:\n(.*?)(?=^  schedule:|^  workflow_dispatch:|^\S)", text)
        self.assertIsNotNone(push)
        self.assertNotIn(".github/workflows/24h_autonomous_research.yml", push.group(1))

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
        self.assertIn("HARD_EXCLUDED = {"baseball", "soccer"}", text)


if __name__ == "__main__":
    unittest.main()
