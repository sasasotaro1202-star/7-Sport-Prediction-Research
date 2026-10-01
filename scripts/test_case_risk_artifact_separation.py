from __future__ import annotations

import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_source_contract():
    strict=(ROOT/'src/research_cycle_strict.py').read_text(encoding='utf-8')
    future=(ROOT/'src/future_predictor.py').read_text(encoding='utf-8')
    gate=(ROOT/'src/production_release_gate.py').read_text(encoding='utf-8')

    ast.parse(strict)
    ast.parse(future)
    ast.parse(gate)

    assert "case_risk_path=MODELS/'case_risk'/f'{s}_current.joblib'" in strict
    assert "joblib.dump(case_risk_payload,case_risk_path)" in strict
    assert "'case_risk_artifact_path':case_risk_ref" in strict
    assert "'case_risk_model':" not in strict

    assert "def _load_case_risk_shadow_artifact" in future
    assert "models/research/case_risk/" in future
    assert "source_model_version" in future
    assert "source_frozen_holdout_registry_hash" in future
    assert "artifact.get('case_risk_model')" not in future

    assert "if 'case_risk_model' in obj:" in gate
    assert "not rel.startswith('models/research/case_risk/')" in gate


if __name__=='__main__':
    test_source_contract()
    print('case-risk artifact separation regression: PASS')
