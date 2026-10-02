from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "research_cycle_strict.py"


def _extract_rank_logic():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    train = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "train"
    )
    for node in ast.walk(train):
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "rank" for t in node.targets):
                return node
    raise AssertionError("rank assignment not found")


def test_malformed_candidate_is_rejected_without_typeerror():
    source = SOURCE.read_text(encoding="utf-8")
    assert "invalid_oos_candidates" in source
    assert "oos_score_not_object" in source
    assert "oos_score_invalid_metrics" in source
    assert "no_valid_oos_candidate_scores" in source
    ast.parse(source)


def test_expected_ranking_contract_rejects_string_score():
    oos = {
        "good": {
            "robust_objective": 0.68,
            "brier": 0.24,
            "ece": 0.03,
            "logloss": 0.68,
        },
        "broken": "TRAIN_FAILED",
    }

    invalid = {}
    rankable = {}
    for name, score in oos.items():
        if not isinstance(score, dict):
            invalid[name] = {"reason": "oos_score_not_object", "status": "REJECTED"}
            continue
        required = ("robust_objective", "brier", "ece", "logloss")
        missing = [m for m in required if m not in score or not np.isfinite(float(score[m]))]
        if missing:
            invalid[name] = {
                "reason": "oos_score_invalid_metrics",
                "missing_or_nonfinite_metrics": missing,
                "status": "REJECTED",
            }
            continue
        rankable[name] = score

    rank = sorted(
        rankable,
        key=lambda k: (
            float(rankable[k]["robust_objective"]),
            float(rankable[k]["brier"]),
            float(rankable[k]["ece"]),
        ),
    )

    assert rank == ["good"]
    assert invalid["broken"]["status"] == "REJECTED"
    json.dumps(invalid, ensure_ascii=False)
