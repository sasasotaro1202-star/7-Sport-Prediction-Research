from __future__ import annotations

from src.prediction_method_policy import select_method


def test_high_confidence_head_to_head_prefers_scalar_probability():
    result = select_method(
        sport="volleyball",
        participant_count=2,
        selected_lead_minutes=30,
        competition_profile={"matched": True, "profile_id": "volleyball:asian_games"},
        strategy="competition_specific_model",
        router_status="COMPETITION_SPECIFIC_ACCEPTED",
        competition_specific=True,
        probability=0.92,
        situation={"status": "PIT_SAFE", "quality": {"evidence_count": 2, "freshness_score": 0.9, "conflict_rate": 0.0}},
        experience_shadow={"recommendation": "PASS"},
    )
    assert result["target"]["type"] == "binary_winner"
    assert result["output"]["format"] == "single_probability"
    assert result["method"]["model_method"] == "competition_specific_model"


def test_uncertain_case_moves_to_set_or_abstain():
    result = select_method(
        sport="ufc",
        participant_count=2,
        selected_lead_minutes=30,
        competition_profile={"matched": True, "profile_id": "ufc:promotion"},
        strategy="fixed_equal_weight",
        router_status="FALLBACK_FIXED_ENSEMBLE",
        competition_specific=False,
        probability=0.53,
        situation={"status": "PIT_SAFE", "quality": {"evidence_count": 1, "freshness_score": 0.8, "conflict_rate": 0.0}, "uncertainty": {"model_disagreement": 0.08}},
        experience_shadow={"recommendation": "EXPERIENCE_REVIEW"},
    )
    assert result["uncertainty"]["level"] == "HIGH"
    assert result["uncertainty"]["predictability_proxy"]["score"] < 0.55
    assert result["uncertainty"]["predictability_proxy"]["calibrated"] is False
    assert result["output"]["format"] in {"prediction_set_or_scenario", "abstain_or_fallback"}
    assert result["output"]["action"] == "PASS"
    assert result["experience"]["review_signal"] is True


def test_experience_never_changes_probability_or_route():
    result = select_method(
        sport="basketball",
        participant_count=2,
        selected_lead_minutes=45,
        competition_profile={"matched": True, "profile_id": "basketball:bleague"},
        strategy="contextual_router",
        router_status="PRODUCTION_ROUTABLE_AFTER_GATES",
        competition_specific=False,
        probability=0.71,
        situation={"status": "PIT_SAFE", "quality": {"evidence_count": 1}},
        experience_shadow={"recommendation": "EXPERIENCE_REVIEW"},
    )
    assert result["method"]["model_method"] == "contextual_router"
    assert result["experience"]["used_to_change_probability"] is False
    assert result["experience"]["used_to_change_model_route"] is False
    assert result["information"]["next_action"] == "study_repeated_error_pattern"
    assert result["output"]["update_action"] == "revise_when_new_information_arrives"


def test_stale_information_requests_refresh():
    result = select_method(
        sport="volleyball",
        participant_count=2,
        selected_lead_minutes=30,
        competition_profile={"matched": True, "profile_id": "volleyball:asian_games"},
        strategy="fixed_equal_weight",
        router_status="FALLBACK_FIXED_ENSEMBLE",
        competition_specific=False,
        probability=0.70,
        situation={"status": "PIT_SAFE", "quality": {"evidence_count": 2, "freshness_score": 0.2, "conflict_rate": 0.0}},
        experience_shadow={"recommendation": "PASS"},
    )
    assert result["information"]["next_action"] == "refresh_pit_safe_sources"


if __name__ == "__main__":
    test_high_confidence_head_to_head_prefers_scalar_probability()
    test_uncertain_case_moves_to_set_or_abstain()
    test_experience_never_changes_probability_or_route()
    test_stale_information_requests_refresh()
    print("prediction_method_policy tests passed")
