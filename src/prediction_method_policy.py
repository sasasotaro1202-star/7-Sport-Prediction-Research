from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "PREDICTION_METHOD_META_POLICY.json"


def _policy() -> dict[str, Any]:
    try:
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError("PREDICTION_METHOD_POLICY_UNAVAILABLE") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("PREDICTION_METHOD_POLICY_INVALID")
    return payload


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


def _target_profile(sport: str, participant_count: int, multiclass: bool) -> tuple[str, dict]:
    policy = _policy()
    profiles = policy["target_profiles"]
    if multiclass:
        return "multiclass_winner", dict(profiles["multiclass_winner"])
    if participant_count == 2:
        return "head_to_head_winner", dict(profiles["head_to_head_winner"])
    return "unsupported_participant_cardinality", {
        "target_type": "unsupported",
        "granularity": "event",
        "output_candidates": ["abstain_or_fallback"],
    }


def _model_method(strategy: str, router_status: str, competition_specific: bool) -> str:
    policy = _policy()["method_preferences"]
    if competition_specific or router_status == "COMPETITION_SPECIFIC_ACCEPTED":
        return str(policy["competition_specific_accepted"])
    if strategy == "contextual_router" or router_status == "PRODUCTION_ROUTABLE_AFTER_GATES":
        return str(policy["contextual_router"])
    if strategy == "safe_prior" or router_status == "SAFE_PRIOR_FALLBACK":
        return str(policy["safe_prior"])
    return str(policy["fixed_ensemble"])


def select_method(
    *,
    sport: str,
    participant_count: int,
    selected_lead_minutes: int,
    competition_profile: dict[str, Any] | None,
    strategy: str,
    router_status: str,
    competition_specific: bool,
    probability: float,
    situation: dict[str, Any] | None,
    experience_shadow: dict[str, Any] | None,
    multiclass: bool = False,
) -> dict[str, Any]:
    policy = _policy()
    selection = policy["selection"]
    situation = situation or {}
    quality = situation.get("quality") or {}
    conflict = _safe_float(quality.get("conflict_rate"))
    freshness = _safe_float(quality.get("freshness_score"))
    evidence = int(quality.get("evidence_count") or 0)

    max_probability = max(float(probability), 1.0 - float(probability))
    if conflict is not None and conflict > float(selection["high_conflict_rate"]):
        confidence = "LOW"
    elif (
        max_probability >= float(selection["confidence_high_probability"])
        and evidence >= int(selection["minimum_evidence_count_for_high_confidence"])
        and (freshness is None or freshness >= float(selection["stale_freshness_score"]))
    ):
        confidence = "HIGH"
    elif max_probability >= float(selection["confidence_medium_probability"]):
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    disagreement = _safe_float((situation.get("uncertainty") or {}).get("model_disagreement"))
    entropy_denominator = math.log(2.0)
    entropy = 0.0
    if 0.0 < float(probability) < 1.0:
        p = float(probability)
        entropy = -(p * math.log(p) + (1.0 - p) * math.log(1.0 - p)) / entropy_denominator
    disagreement_component = 0.0 if disagreement is None else min(max(disagreement * 4.0, 0.0), 1.0)
    predictability = max(
        0.0,
        min(
            1.0,
            1.0
            - float(selection["predictability_entropy_weight"]) * entropy
            - float(selection["predictability_disagreement_weight"]) * disagreement_component,
        ),
    )
    if (
        predictability < float(selection["predictability_medium"])
        or (disagreement is not None and disagreement >= float(selection["high_disagreement"]))
        or confidence == "LOW"
    ):
        uncertainty = "HIGH"
    elif predictability < float(selection["predictability_high"]) or confidence == "MEDIUM":
        uncertainty = "MEDIUM"
    else:
        uncertainty = "LOW"

    if confidence == "LOW" or uncertainty == "HIGH" or (conflict is not None and conflict > float(selection["high_conflict_rate"])):
        output = "abstain_or_fallback" if confidence == "LOW" else "prediction_set_or_scenario"
        action = str(selection["low_confidence_action"])
        refresh = "refresh_or_recompute_candidate"
    elif uncertainty == "MEDIUM":
        output = "probability_plus_uncertainty"
        action = str(selection["medium_confidence_action"])
        refresh = "refresh_when_new_information_has_expected_value"
    else:
        output = "probability_distribution" if multiclass else "single_probability"
        action = str(selection["high_confidence_action"])
        refresh = "maintain_until_selected_cutoff"

    matched_profile = bool((competition_profile or {}).get("matched"))
    profile_id = str((competition_profile or {}).get("profile_id") or "UNKNOWN")
    model_method = _model_method(strategy, router_status, competition_specific)

    experience = experience_shadow or {}
    experience_review = str(experience.get("recommendation") or "PASS") == "EXPERIENCE_REVIEW"

    information_action = "maintain"
    if conflict is not None and conflict > float(selection["high_conflict_rate"]):
        information_action = "verify_or_resolve_conflicting_sources"
    elif freshness is not None and freshness < float(selection["stale_freshness_score"]):
        information_action = "refresh_pit_safe_sources"
    elif experience_review:
        information_action = "study_repeated_error_pattern"
    elif uncertainty == "HIGH":
        information_action = "acquire_high_value_information_candidate"

    update_action = (
        "abstain_or_fallback"
        if confidence == "LOW"
        else "recompute_candidate"
        if uncertainty == "HIGH"
        else "revise_when_new_information_arrives"
        if uncertainty == "MEDIUM"
        else "maintain"
    )

    target_profile_id, target_profile = _target_profile(sport, participant_count, multiclass)
    policy_hash = hashlib.sha256(
        json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return {
        "version": "prediction-method-meta-policy-v1",
        "policy_hash": policy_hash,
        "status": "SELECTED",
        "sport": sport,
        "target": {
            "profile": target_profile_id,
            "type": target_profile["target_type"],
            "granularity": target_profile["granularity"],
        },
        "horizon": {
            "kind": "event_relative_lead_minutes",
            "selected_lead_minutes": int(selected_lead_minutes),
        },
        "scope": {
            "competition_profile_id": profile_id,
            "competition_profile_matched": matched_profile,
        },
        "information": {
            "policy": "PIT_PRE_CUTOFF_ONLY",
            "matchday_information_status": str(situation.get("status") or "UNAVAILABLE"),
            "evidence_count": evidence,
            "freshness_score": freshness,
            "conflict_rate": conflict,
            "next_action": information_action,
        },
        "method": {
            "model_method": model_method,
            "strategy": strategy,
            "router_status": router_status,
            "competition_specific": bool(competition_specific),
        },
        "uncertainty": {
            "confidence": confidence,
            "model_disagreement": disagreement,
            "predictability_proxy": {
                "score": predictability,
                "method": "entropy_disagreement_proxy",
                "calibrated": False,
            },
            "level": uncertainty,
        },
        "output": {
            "format_candidate": output,
            "action": action,
            "refresh_policy": refresh,
            "update_action": update_action,
        },
        "experience": {
            "shadow_only": True,
            "review_signal": experience_review,
            "used_to_change_probability": False,
            "used_to_change_model_route": False,
        },
        "safety": {
            "production_auto_promotion": False,
            "fallback_on_invalid_pit_or_missing_features": True,
        },
    }


__all__ = ["select_method"]
