from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "COMPETITION_PROFILE_POLICY.json"


def _load() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def normalize(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def resolve_profile(sport: str, competition_id: object = None, event_name: object = None, research_discovery: bool = False) -> dict:
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
                "dynamic": False,
                "competition_id": str(competition_id or ""),
                "canonical_competition_id": str(
                    profile.get("canonical_competition_id") or profile["profile_id"]
                ),
            }
    dynamic = {str(x) for x in (policy.get("dynamic_competition_discovery") or [])}
    if (str(sport) in dynamic or research_discovery) and cid:
        base_profile = next(
            (p for p in policy.get("profiles", []) if str(p.get("sport")) == str(sport)),
            None,
        )
        if base_profile:
            safe_id = re.sub(r"[^a-z0-9]+", "_", cid).strip("_")[:80] or "unknown"
            return {
                "profile_id": f"{sport}:competition:{safe_id}",
                "sport": str(sport),
                "phase_type": str(base_profile.get("phase_type") or "competition"),
                "rules_profile": str(base_profile.get("rules_profile") or "standard"),
                "matched": True,
                "dynamic": True,
                "competition_id": str(competition_id or ""),
                "canonical_competition_id": f"{sport}:competition:{safe_id}",
            }
    return {
        "profile_id": None,
        "sport": str(sport),
        "phase_type": "unknown",
        "rules_profile": "unknown",
        "matched": False,
        "dynamic": False,
        "competition_id": str(competition_id or ""),
        "canonical_competition_id": None,
    }


def resolve_research_profile(sport: str, competition_id: object = None, event_name: object = None) -> dict:
    """Resolve an explicit competition identity for research only; this never changes production scope."""
    return resolve_profile(sport, competition_id, event_name, research_discovery=True)


def _normalise_context(value: object) -> str:
    value = normalize(value)
    return re.sub(r"[^a-z0-9._-]+", "_", value).strip("_")


def segment_policy(sport: str) -> dict:
    policy = _load()
    configured = dict((policy.get("segment_policy") or {}).get(str(sport)) or {})
    return {
        "levels": list(configured.get("levels") or ["competition"]),
        "minimum_explicit_context": int(configured.get("minimum_explicit_context", 0)),
        "max_depth": int(configured.get("max_depth", 6)),
    }


def build_segment_candidates(
    profile: dict,
    *,
    sport: str,
    season: object = None,
    stage: object = None,
    round_: object = None,
    event_type: object = None,
) -> list[dict]:
    """Build most-specific-to-broad immutable segment identities.

    Only explicit event metadata participates. Missing fields are not inferred.
    The first element is the most specific feasible segment and later elements
    are deterministic ancestors used as data-sufficiency fallbacks.
    """
    if not profile or not profile.get("matched") or not profile.get("profile_id"):
        return []

    cfg = segment_policy(sport)
    raw = {
        "season": _normalise_context(season),
        "stage": _normalise_context(stage),
        "round": _normalise_context(round_),
        "event_type": _normalise_context(event_type),
    }
    levels = [str(x) for x in cfg["levels"] if str(x) in raw]
    explicit_levels = [x for x in levels if raw[x]]
    if len(explicit_levels) < int(cfg["minimum_explicit_context"]):
        explicit_levels = explicit_levels[: max(0, int(cfg["minimum_explicit_context"]))]
    explicit_levels = explicit_levels[: max(0, int(cfg["max_depth"]))]

    base = str(profile["profile_id"])
    candidates = []
    seen = set()
    # Use only explicit fields and build a prefix hierarchy. This avoids an
    # arbitrary powerset of contexts while still allowing season-only routing
    # when stage/round are absent.
    for depth in range(len(explicit_levels), -1, -1):
        parts = [base]
        for level in explicit_levels[:depth]:
            parts.append(f"{level}={raw[level]}")
        key = "::".join(parts)
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "segment_id": key,
            "profile_id": str(profile["profile_id"]),
            "sport": str(sport),
            "specificity": depth,
            "context": {x: raw[x] for x in explicit_levels[:depth]},
        })
    return candidates


def profile_policy() -> dict:
    return _load()


__all__ = [
    "normalize",
    "resolve_profile",
    "resolve_research_profile",
    "segment_policy",
    "build_segment_candidates",
    "profile_policy",
]
