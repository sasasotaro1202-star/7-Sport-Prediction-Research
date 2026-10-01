from __future__ import annotations

import numpy as np

from src.future_predictor import _case_risk_shadow


class _FakeRiskModel:
    def __init__(self):
        self.calls = 0

    def predict_proba(self, X):
        self.calls += 1
        return np.asarray([[0.20, 0.80]], dtype=float)


def _inputs():
    rng = np.random.default_rng(20261002)
    history = rng.normal(size=(180, 4))
    current = rng.normal(size=(1, 4))
    return history, current, [0.0] * 20


def test_case_risk_shadow_is_available_and_advisory():
    history, current, matchday = _inputs()
    model = _FakeRiskModel()
    result = _case_risk_shadow(
        model_bundle={'model': model, 'kind': 'fake', 'policy': 'pre_holdout_oos_only'},
        model_names=['a', 'b'],
        risk_predictions={'a': 0.80, 'b': 0.60},
        baseline_weights={'a': 0.5, 'b': 0.5},
        history_X=history,
        current_X=current,
        matchday_context=matchday,
        selected_lead_minutes=60,
    )
    assert result['status'] == 'SHADOW'
    assert 0.0 < result['error_probability'] < 1.0
    assert result['baseline_probability_reference'] == 0.70
    assert result['used_to_change_probability'] is False
    assert result['used_to_change_model_route'] is False
    assert result['used_to_change_action'] is False
    assert model.calls == 1


def test_case_risk_shadow_blocks_future_matchday_context_before_t60():
    history, current, matchday = _inputs()
    model = _FakeRiskModel()
    result = _case_risk_shadow(
        model_bundle={'model': model},
        model_names=['a', 'b'],
        risk_predictions={'a': 0.80, 'b': 0.60},
        baseline_weights={'a': 0.5, 'b': 0.5},
        history_X=history,
        current_X=current,
        matchday_context=matchday,
        selected_lead_minutes=90,
    )
    assert result['status'] == 'PIT_BLOCKED'
    assert model.calls == 0


if __name__ == '__main__':
    test_case_risk_shadow_is_available_and_advisory()
    test_case_risk_shadow_blocks_future_matchday_context_before_t60()
    print('case-risk shadow bridge tests passed')
