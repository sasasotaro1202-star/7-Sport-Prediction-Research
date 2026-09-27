from __future__ import annotations

import json
from pathlib import Path
import tempfile

import scripts.discover_scope_expansion as discovery
from scripts.discover_scope_expansion import _active_leagues, _items, _league_summary, discover_candidate

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "SCOPE_EXPANSION_FRONTIER.json"


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    candidates = cfg["expansion_candidates"]
    assert cfg["policy"]["free_only"] is True
    sports = [str(x["sport"]) for x in candidates]
    assert len(sports) == len(set(sports))
    assert "baseball" not in sports
    assert "soccer" not in sports
    assert "baseball" in cfg["excluded_sports"]
    assert "soccer" in cfg["excluded_sports"]
    assert len(cfg.get("source_probe_candidates") or []) >= 10
    assert all(str(x["status"]) == "DISCOVERY_ONLY" for x in candidates)
    assert len(cfg.get("source_probe_candidates") or []) >= 17
    assert all(str(x.get("sport")) not in {"baseball", "soccer"} for x in cfg.get("source_probe_candidates") or [])
    assert "badminton" in sports
    assert "table-tennis" in sports

    # Hard exclusions must also hold at the function boundary, not only in
    # config filtering, so direct/in-process discovery cannot rediscover them.
    for excluded_sport in ("baseball", "soccer"):
        result = discover_candidate({"sport": excluded_sport, "provider": "espn", "espn_slug": excluded_sport})
        assert result["status"] == "EXCLUDED_SPORT"
        assert result["sport"] == excluded_sport
        assert result["pit_status"] == "UNPROVEN"
        assert result["research_only"] is True
        assert result["production_model_touched"] is False

    sample = {"items": [{"id": "10", "slug": "demo", "name": "Demo League", "abbreviation": "DL", "isTournament": True}]}
    rows = _items(sample)
    assert len(rows) == 1
    summary = _league_summary(rows[0])
    assert summary["slug"] == "demo"
    assert summary["name"] == "Demo League"
    assert summary["classification"]["competition_type"] == "domestic_league"

    header = {"sports": [{"leagues": [{"id": "10", "name": "Demo League", "slug": "demo", "events": [{"id": "e1"}, {"id": "e2"}]}]}]}
    active = _active_leagues(header)
    assert len(active) == 1
    assert active[0]["id"] == "10"
    assert active[0]["name"] == "Demo League"
    assert active[0]["slug"] == "demo"
    assert active[0]["event_count"] == 2
    assert active[0]["classification"]["competition_type"] == "domestic_league"

    original_nhl = discovery.discover_nhl
    try:
        discovery.discover_nhl = lambda sport: {
            "sport": sport, "provider": "nhl_official",
            "status": "DISCOVERED", "pit_status": "UNPROVEN",
            "research_only": True, "production_model_touched": False,
        }
        nhl_result = discover_candidate({"sport": "hockey", "provider": "nhl_official"})
        assert nhl_result["provider"] == "nhl_official"
        assert nhl_result["pit_status"] == "UNPROVEN"
    finally:
        discovery.discover_nhl = original_nhl
    ref_result = discover_candidate({"sport": "handball", "provider": "reference_only", "reference_url": "https://github.com/nmjohnson/handball-rapm"})
    assert ref_result["status"] == "REFERENCE_CANDIDATE"

    original_openwec = discovery.discover_openwec
    try:
        discovery.discover_openwec = lambda sport: {
            "sport": sport, "provider": "openwec",
            "status": "DISCOVERED", "pit_status": "UNPROVEN",
            "research_only": True, "production_model_touched": False,
        }
        openwec_result = discover_candidate({"sport": "wec", "provider": "openwec"})
        assert openwec_result["provider"] == "openwec"
        assert openwec_result["pit_status"] == "UNPROVEN"
    finally:
        discovery.discover_openwec = original_openwec

    original_dota = discovery.discover_opendota
    try:
        discovery.discover_opendota = lambda sport: {
            "sport": sport, "provider": "opendota",
            "status": "DISCOVERED", "pit_status": "UNPROVEN",
            "research_only": True, "production_model_touched": False,
        }
        dota_result = discover_candidate({"sport": "dota-2", "provider": "opendota"})
        assert dota_result["provider"] == "opendota"
        assert dota_result["pit_status"] == "UNPROVEN"
    finally:
        discovery.discover_opendota = original_dota

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "out.json"
        p.write_text(json.dumps({"pit_status": "UNPROVEN"}), encoding="utf-8")
        assert json.loads(p.read_text(encoding="utf-8"))["pit_status"] == "UNPROVEN"

    print("SCOPE_EXPANSION_CONFIG=PASS")
    print("SCOPE_EXPANSION_PARSER=PASS")
    print("SCOPE_EXPANSION_HARD_EXCLUSION=PASS")
    print("SCOPE_EXPANSION_PIT_DEFAULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
