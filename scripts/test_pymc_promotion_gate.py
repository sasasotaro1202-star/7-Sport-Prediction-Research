import json
import tempfile
from pathlib import Path

from scripts.pymc_promotion_gate import evaluate

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    sha = "test-head"
    report = evaluate(root, sha)
    assert report["status"] == "HOLD"
    assert "MISSING_REQUIRED_EVIDENCE" == report["reason"]
    assert report["production"] is False
    assert report["automatic_promotion"] is False

    for name in ("wfo", "calibration", "ablation", "robustness", "holdout", "shadow", "pit_audit"):
        (root / f"{name}.json").write_text(
            json.dumps({
                "github_head_sha": sha,
                "production_dependency": False,
                "automatic_promotion": False,
                "performance_verification": True,
                "status": "PASS",
                "pit_violation_count": 0,
                "used_for_selection": False,
                "used_for_tuning": False,
            }),
            encoding="utf-8",
        )
    report = evaluate(root, sha)
    assert report["status"] == "HOLD"
    assert report["reason"].endswith("_NOT_VERIFIED") or report["reason"] == "WFO_NOT_VERIFIED"

print("PYMC_PROMOTION_GATE_FAIL_CLOSED_CONTRACT=PASS")
