from __future__ import annotations

import argparse
import json
from pathlib import Path

PRIMARY_RELATIVE_IMPROVEMENT = 0.03
SECONDARY_RELATIVE_IMPROVEMENT = 0.01
MIN_WFO_FOLD_FRACTION = 0.70
MAX_CALIBRATION_REGRESSION = 0.0
MAX_HOLDOUT_REGRESSION = 0.0
MAX_SHADOW_REGRESSION = 0.0


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def current_sha_for(evidence: dict) -> str | None:
    return (
        evidence.get("github_head_sha")
        or evidence.get("head_sha")
        or evidence.get("source_git_commit_sha")
    )


def fail(reason: str, missing: list[str] | None = None, reject: bool = False) -> dict:
    return {
        "status": "REJECTED" if reject else "HOLD",
        "promotion_status": "REJECTED" if reject else "HOLD",
        "reason": reason,
        "missing_evidence": missing or [],
        "production": False,
        "automatic_promotion": False,
    }


def evaluate(evidence_dir: Path, expected_head_sha: str) -> dict:
    required = {
        "wfo": evidence_dir / "wfo.json",
        "calibration": evidence_dir / "calibration.json",
        "ablation": evidence_dir / "ablation.json",
        "robustness": evidence_dir / "robustness.json",
        "holdout": evidence_dir / "holdout.json",
        "shadow": evidence_dir / "shadow.json",
        "pit_audit": evidence_dir / "pit_audit.json",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        return {
            **fail("MISSING_REQUIRED_EVIDENCE", missing=missing),
            "candidate": "pymc-devs/pymc",
            "expected_head_sha": expected_head_sha,
        }

    data = {name: read_json(path) for name, path in required.items()}

    for name, obj in data.items():
        sha = current_sha_for(obj)
        if sha != expected_head_sha:
            return fail(
                f"STALE_OR_UNVERIFIABLE_{name.upper()}_SHA",
                reject=True,
            )
        if obj.get("production_dependency") is True or obj.get("automatic_promotion") is True:
            return fail(
                f"UNSAFE_{name.upper()}_PRODUCTION_FLAGS",
                reject=True,
            )

    pit = data["pit_audit"]
    if pit.get("status") != "PASS" or int(pit.get("pit_violation_count", 0)) != 0:
        return fail("PIT_GATE_FAIL", reject=True)

    holdout = data["holdout"]
    if holdout.get("used_for_selection") is True:
        return fail("HOLDOUT_USED_FOR_SELECTION", reject=True)
    if holdout.get("used_for_tuning") is True:
        return fail("HOLDOUT_USED_FOR_TUNING", reject=True)

    wfo = data["wfo"]
    if wfo.get("status") != "WFO_PERFORMANCE_OBSERVED":
        return fail("WFO_NOT_VERIFIED")
    wfo_rel = float(
        wfo.get("aggregate", {}).get(
            "candidate_relative_logloss_improvement_vs_incumbent",
            -1.0,
        )
    )
    folds = int(wfo.get("aggregate", {}).get("fold_count", 0))
    better = int(
        wfo.get("aggregate", {}).get(
            "folds_better_than_incumbent",
            0,
        )
    )
    if wfo_rel < PRIMARY_RELATIVE_IMPROVEMENT:
        return fail("PRIMARY_WFO_IMPROVEMENT_GATE_FAIL")
    if float(
        wfo.get("aggregate", {}).get("candidate_secondary_relative_improvement", -1.0)
    ) < SECONDARY_RELATIVE_IMPROVEMENT:
        return fail("SECONDARY_WFO_IMPROVEMENT_GATE_FAIL")
    if folds <= 0 or better / folds < MIN_WFO_FOLD_FRACTION:
        return fail("WFO_PERIOD_CONSISTENCY_GATE_FAIL")

    calibration = data["calibration"]
    cal_rel = float(calibration.get("relative_ece_improvement", -1.0))
    cal_reg = float(calibration.get("candidate_minus_incumbent_ece", float("inf")))
    if not (cal_rel >= 0.10 or cal_reg <= MAX_CALIBRATION_REGRESSION):
        return fail("CALIBRATION_GATE_FAIL")

    ablation = data["ablation"]
    if ablation.get("incremental_value_verified") is not True:
        return fail("ABLATION_GATE_FAIL")

    robustness = data["robustness"]
    if robustness.get("robustness_verified") is not True:
        return fail("ROBUSTNESS_GATE_FAIL")
    if float(robustness.get("worst_case_delta_logloss", float("inf"))) > 0.0:
        return fail("ROBUSTNESS_WORST_CASE_REGRESSION")

    hold_delta = float(holdout.get("candidate_minus_incumbent_logloss", float("inf")))
    if hold_delta > MAX_HOLDOUT_REGRESSION:
        return fail("FROZEN_HOLDOUT_REGRESSION")
    if holdout.get("performance_verified") is not True:
        return fail("FROZEN_HOLDOUT_NOT_VERIFIED")

    shadow = data["shadow"]
    if shadow.get("comparison_verified") is not True:
        return fail("SHADOW_COMPARISON_NOT_VERIFIED")
    if float(shadow.get("candidate_minus_incumbent_logloss", float("inf"))) > MAX_SHADOW_REGRESSION:
        return fail("SHADOW_REGRESSION")
    if shadow.get("operational_regression") is True:
        return fail("SHADOW_OPERATIONAL_REGRESSION")

    if any(obj.get("performance_verification") is False for obj in data.values()):
        return fail("PERFORMANCE_VERIFICATION_FLAG_FALSE")

    return {
        "status": "PROMOTION_CANDIDATE",
        "promotion_status": "PROMOTION_CANDIDATE",
        "candidate": "pymc-devs/pymc",
        "expected_head_sha": expected_head_sha,
        "production": False,
        "automatic_promotion": False,
        "decision": "EXPLICIT_HUMAN_OR_PROJECT_GATE_REQUIRED",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-dir", type=Path, required=True)
    ap.add_argument("--expected-head-sha", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    report = evaluate(args.evidence_dir, args.expected_head_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"HOLD", "PROMOTION_CANDIDATE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
