from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "PROJECT_SCOPE_POLICY.json"


class ProjectScopeBoundaryTests(unittest.TestCase):
    def test_reference_only_policy_is_explicit(self):
        cfg = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertFalse(cfg["production_mutation"])
        self.assertFalse(cfg["scope_pooling"])
        self.assertEqual(
            set(cfg["reference_only_projects"]),
            {"soccer", "baseball"},
        )

    def test_active_scope_matches_policy(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        scope = json.loads(
            (ROOT / "config" / "ACTIVE_SCOPE_9_SPORTS.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            set((scope.get("active_scope") or {}).keys()),
            set(policy["active_prediction_scope"]),
        )
        self.assertNotIn("soccer", scope.get("active_scope", {}))
        self.assertNotIn("baseball", scope.get("active_scope", {}))

    def test_stage_mapping_contains_only_active_prediction_sports(self):
        text = (ROOT / "scripts" / "run_24h_research_stage_main.py").read_text(
            encoding="utf-8"
        )
        stage_sports = set(re.findall(r'STAGE_SPORTS = {[^}]*}', text, flags=re.S))
        self.assertEqual(len(stage_sports), 1)
        self.assertNotIn('"soccer"', text[text.index("STAGE_SPORTS"):text.index("STAGE_SPORTS") + 200])
        self.assertNotIn('"baseball"', text[text.index("STAGE_SPORTS"):text.index("STAGE_SPORTS") + 200])

    def test_no_direct_reference_only_collectors_in_active_pipeline(self):
        roots = [
            ROOT / "src",
            ROOT / "config",
            ROOT / ".github" / "workflows",
        ]
        forbidden = [
            re.compile(r'(?:import|from)s+S*(?:baseball|soccer)S*', re.I),
            re.compile(r'--sports+(?:baseball|soccer)', re.I),
            re.compile(r'(?:baseball|soccer)_(?:collector|backfill|features?|model|train)', re.I),
        ]
        allow_paths = {
            ROOT / "config" / "PROJECT_SCOPE_POLICY.json",
        }
        violations = []
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in {".py", ".json", ".yml", ".yaml"}:
                    continue
                if path in allow_paths or path.name.startswith("test_scope_boundary"):
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                for rx in forbidden:
                    if rx.search(text):
                        violations.append(str(path.relative_to(ROOT)))
                        break
        self.assertEqual(violations, [], f"reference-only integration detected: {violations}")


if __name__ == "__main__":
    unittest.main()
