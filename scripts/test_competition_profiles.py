#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from src.competition_profiles import resolve_profile, profile_policy


def main() -> int:
    assert resolve_profile("basketball", "B.LEAGUE", "league match")["profile_id"] == "basketball:bleague"
    assert resolve_profile("basketball", "Asian Games", "Asian Games Basketball")["profile_id"] == "basketball:asian_games"
    assert resolve_profile("volleyball", "Asian Games Volleyball", "match")["profile_id"] == "volleyball:asian_games"
    assert resolve_profile("ufc", "UFC", "UFC 300")["phase_type"] == "promotion"
    unknown = resolve_profile("basketball", "", "ordinary unknown competition")
    assert unknown["matched"] is False
    dynamic = resolve_profile("valorant", "VCT Champions 2026", "team match")
    assert dynamic["matched"] is True
    assert dynamic["dynamic"] is True
    assert dynamic["profile_id"] == "valorant:competition:vct_champions_2026"
    policy = profile_policy()
    assert policy["no_implicit_pooling"] is True
    assert policy["production_route_enabled"] is False
    assert "valorant" in policy["dynamic_competition_discovery"]
    assert policy["selection"]["require_holdout_before_production"] is True
    gate = (Path(__file__).resolve().parents[1] / "src/production_release_gate.py").read_text(encoding="utf-8")
    assert "meta.setdefault('sport',sport)" in gate
    print("COMPETITION_PROFILE_RESOLVER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
