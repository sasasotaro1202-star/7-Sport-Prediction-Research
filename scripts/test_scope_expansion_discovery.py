from __future__ import annotations

import json
from pathlib import Path
import tempfile

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

    sample = {"items": [{"id": "10", "slug": "demo", "name": "Demo League", "abbreviation": "DL", "isTournament": True}]}
    rows = _items(sample)
    assert len(rows) == 1
    summary = _league_summary(rows[0])
    assert summary["slug"] == "demo"
    assert summary["name"] == "Demo League"

    header = {"sports": [{"leagues": [{"id": "10", "name": "Demo League", "slug": "demo", "events": [{"id": "e1"}, {"id": "e2"}]}]}]}
    active = _active_leagues(header)
    assert active == [{"id": "10", "name": "Demo League", "slug": "demo", "event_count": 2}]

    nhl_result = discover_candidate({"sport": "hockey", "provider": "nhl_official"})
    assert nhl_result["provider"] == "nhl_official"
    assert nhl_result["pit_status"] == "UNPROVEN"
    ref_result = discover_candidate({"sport": "handball", "provider": "reference_only", "reference_url": "https://github.com/nmjohnson/handball-rapm"})
    assert ref_result["status"] == "REFERENCE_CANDIDATE"

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "out.json"
        p.write_text(json.dumps({"pit_status": "UNPROVEN"}), encoding="utf-8")
        assert json.loads(p.read_text(encoding="utf-8"))["pit_status"] == "UNPROVEN"

    print("SCOPE_EXPANSION_CONFIG=PASS")
    print("SCOPE_EXPANSION_PARSER=PASS")
    print("SCOPE_EXPANSION_PIT_DEFAULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
