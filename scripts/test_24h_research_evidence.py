from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.verify_24h_research_evidence as verifier


class VerifyEvidenceTests(unittest.TestCase):
    def _write_case(self, root: Path, primary: dict, v13: dict, intelligence: dict) -> None:
        results = root / "results" / "research"
        artifact = root / "models" / "research"
        results.mkdir(parents=True, exist_ok=True)
        artifact.mkdir(parents=True, exist_ok=True)
        (artifact / "basketball_current.joblib").write_bytes(b"x")
        (results / "basketball.json").write_text(json.dumps(primary), encoding="utf-8")
        (results / "basketball_ultimate_v13.json").write_text(json.dumps(v13), encoding="utf-8")
        (results / "basketball_ultimate_intelligence.json").write_text(
            json.dumps(intelligence), encoding="utf-8"
        )

    def test_valid_case(self):
        sha = "abc123"
        with tempfile.TemporaryDirectory() as td, patch.object(verifier, "ROOT", Path(td)), patch.object(
            verifier, "RESULTS", Path(td) / "results" / "research"
        ), patch.object(verifier, "current_sha", return_value=sha):
            primary = {
                "sport": "basketball",
                "status": "TRAINED",
                "git_commit_sha": sha,
                "artifact_path": "models/research/basketball_current.joblib",
                "holdout_frozen": True,
                "production_fit_excludes_holdout": True,
            }
            v13 = {"sport": "basketball", "status": "EVALUATED"}
            intelligence = {
                "sport": "basketball",
                "mode": "RESEARCH_ONLY",
                "promotion_status": "HOLD_RESEARCH_ONLY_NO_AUTO_PROMOTION",
            }
            self._write_case(Path(td), primary, v13, intelligence)
            out = verifier.verify("basketball")
            self.assertEqual(out["primary_status"], "TRAINED")
            self.assertEqual(out["v13_status"], "EVALUATED")

    def test_stale_git_sha_fails_closed(self):
        sha = "new-sha"
        with tempfile.TemporaryDirectory() as td, patch.object(verifier, "ROOT", Path(td)), patch.object(
            verifier, "RESULTS", Path(td) / "results" / "research"
        ), patch.object(verifier, "current_sha", return_value=sha):
            primary = {
                "sport": "basketball",
                "status": "TRAINED",
                "git_commit_sha": "old-sha",
                "artifact_path": "models/research/basketball_current.joblib",
                "holdout_frozen": True,
                "production_fit_excludes_holdout": True,
            }
            v13 = {"sport": "basketball", "status": "EVALUATED"}
            intelligence = {
                "sport": "basketball",
                "mode": "RESEARCH_ONLY",
                "promotion_status": "HOLD_RESEARCH_ONLY_NO_AUTO_PROMOTION",
            }
            self._write_case(Path(td), primary, v13, intelligence)
            with self.assertRaises(RuntimeError):
                verifier.verify("basketball")


if __name__ == "__main__":
    unittest.main()
