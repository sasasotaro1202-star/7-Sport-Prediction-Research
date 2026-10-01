from __future__ import annotations

import json
import os
from pathlib import Path

import joblib

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "results/research/competition_routes.json"


def _allowed_sports() -> set[str]:
    try:
        policy = json.loads((ROOT / "config/PROJECT_SCOPE_POLICY.json").read_text(encoding="utf-8"))
        return {str(x) for x in (policy.get("active_prediction_scope") or [])}
    except Exception:
        return set()


def load_registry() -> dict:
    if not REGISTRY.is_file() or REGISTRY.stat().st_size <= 0:
        return {"status": "MISSING", "routes": {}}
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "INVALID", "routes": {}}
    if not isinstance(data, dict) or not isinstance(data.get("routes", {}), dict):
        return {"status": "INVALID", "routes": {}}
    return data


def _route_is_usable(route: dict, sport: str, profile: dict) -> bool:
    if not isinstance(route, dict):
        return False
    if str(route.get("quality_status")) != "ACCEPTED_LOCKED_HOLDOUT":
        return False
    if str(route.get("model_scope")) != "competition_specific;frozen_holdout_accepted":
        return False
    if str(route.get("sport")) != str(sport):
        return False
    if str(route.get("profile_id")) != str(profile.get("profile_id")):
        return False
    if not str(route.get("artifact_path") or "").startswith("models/competition/"):
        return False
    artifact = ROOT / str(route["artifact_path"])
    if not artifact.is_file() or artifact.stat().st_size <= 0:
        return False
    if str(route.get("git_commit_sha") or "") in {"", "UNKNOWN_UNVERIFIED"}:
        return False
    if route.get("holdout_used_for_selection", False):
        return False
    holdout = route.get("holdout") or {}
    if not isinstance(holdout, dict) or int(holdout.get("n", 0) or 0) < 30:
        return False
    return True


def resolve_route(sport: str, profile: dict):
    active = _allowed_sports()
    if sport not in active:
        return None
    if not profile or not profile.get("matched") or not profile.get("profile_id"):
        return None
    registry = load_registry()
    if registry.get("status") not in {"READY", "READY_NO_ACCEPTED_ROUTES"}:
        return None
    route = registry.get("routes", {}).get(str(profile["profile_id"]))
    if not _route_is_usable(route, sport, profile):
        return None
    artifact_path = ROOT / str(route["artifact_path"])
    try:
        model = joblib.load(artifact_path)
    except Exception:
        return None
    return {"route": route, "model": model}


def route_status(sport: str, profile: dict) -> str:
    resolved = resolve_route(sport, profile)
    return "COMPETITION_SPECIFIC_ACCEPTED" if resolved else "SPORT_INCUMBENT_FALLBACK"


__all__ = ["load_registry", "resolve_route", "route_status"]
