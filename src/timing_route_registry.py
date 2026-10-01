from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "results/research/timing_routes.json"
DEFAULT_LEAD = 30


def load_registry() -> dict:
    if not REGISTRY.is_file() or REGISTRY.stat().st_size <= 0:
        return {"status": "MISSING", "routes": {}}
    try:
        value = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "INVALID", "routes": {}}
    if not isinstance(value, dict) or not isinstance(value.get("routes", {}), dict):
        return {"status": "INVALID", "routes": {}}
    return value


def resolve_lead(sport: str, profile: dict, default: int = DEFAULT_LEAD) -> tuple[int, str]:
    profile_id = str((profile or {}).get("profile_id") or "")
    if not profile_id or not (profile or {}).get("matched"):
        return int(default), "DEFAULT_GUIDELINE"

    registry = load_registry()
    if registry.get("status") not in {"READY", "READY_NO_ACCEPTED_ROUTES"}:
        return int(default), "DEFAULT_GUIDELINE"
    route = registry.get("routes", {}).get(profile_id)
    if not isinstance(route, dict):
        return int(default), "DEFAULT_GUIDELINE"
    if str(route.get("quality_status")) != "ACCEPTED_LOCKED_HOLDOUT":
        return int(default), "DEFAULT_GUIDELINE"
    if str(route.get("model_scope")) != "timing_policy;competition_specific;frozen_holdout_accepted":
        return int(default), "DEFAULT_GUIDELINE"
    if str(route.get("pit_status")) != "REQUIRED_CLEAN_BY_PRODUCTION_TIMING_GATE":
        return int(default), "DEFAULT_GUIDELINE"
    if bool(route.get("holdout_used_for_selection", False)):
        return int(default), "DEFAULT_GUIDELINE"
    if str(route.get("sport")) != str(sport):
        return int(default), "DEFAULT_GUIDELINE"
    try:
        lead = int(route.get("selected_lead_minutes"))
    except (TypeError, ValueError):
        return int(default), "DEFAULT_GUIDELINE"
    policy_path = ROOT / "config/PREDICTION_TIMING_POLICY.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        allowed = {int(x) for x in policy.get("allowed_lead_minutes", [])}
    except Exception:
        allowed = set()
    if lead not in allowed:
        return int(default), "DEFAULT_GUIDELINE"
    if int(route.get("holdout", {}).get("n", 0) or 0) < 30:
        return int(default), "DEFAULT_GUIDELINE"
    return lead, "TIMING_ROUTE_ACCEPTED"


__all__ = ["load_registry", "resolve_lead"]
