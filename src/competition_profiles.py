from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "COMPETITION_PROFILE_POLICY.json"


def _load() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def normalize(value: object) -> str:
    return re.sub(r"\\s+", " ", str(value or "")).strip().lower()


def resolve_profile(sport: str, competition_id: object = None, event_name: object = None) -> dict:
    policy = _load()
    cid = normalize(competition_id)
    name = normalize(event_name)
    haystack = " | ".join(x for x in (cid, name) if x)
    for profile in policy.get("profiles", []):
        if str(profile.get("sport")) != str(sport):
            continue
        aliases = [normalize(x) for x in (profile.get("aliases") or []) if normalize(x)]
        if any(alias in haystack for alias in aliases):
            return {
                "profile_id": str(profile["profile_id"]),
                "sport": str(profile["sport"]),
                "phase_type": str(profile.get("phase_type") or "unknown"),
                "rules_profile": str(profile.get("rules_profile") or "standard"),
                "matched": True,
                "competition_id": str(competition_id or ""),
            }
    return {
        "profile_id": None,
        "sport": str(sport),
        "phase_type": "unknown",
        "rules_profile": "unknown",
        "matched": False,
        "competition_id": str(competition_id or ""),
    }


def profile_policy() -> dict:
    return _load()


__all__ = ["normalize", "resolve_profile", "profile_policy"]
