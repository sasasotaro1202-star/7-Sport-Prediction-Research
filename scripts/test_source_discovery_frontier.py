from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTIER = ROOT / "config" / "SOURCE_DISCOVERY_FRONTIER_9.json"


def main() -> int:
    cfg = json.loads(FRONTIER.read_text(encoding="utf-8"))
    policy = cfg["policy"]
    assert policy["free_only"] is True
    assert policy["no_trial_auto_use"] is True
    assert policy["no_billing_risk"] is True
    rows = cfg["frontier"]
    assert len(rows) >= 10
    ids = {row["id"] for row in rows}
    assert "thesportsdb" in ids
    assert "espn_public" in ids
    assert "odds_api_io" in ids
    assert "sofascore" in ids
    blocked = {row["id"]: row["status"] for row in rows if row["status"].startswith("blocked") or row["status"] == "do_not_use_for_production"}
    assert "pinnapi" in blocked
    assert "pinnwire" in blocked
    assert "tennis_data_uk" in blocked
    assert all(not (row["status"].startswith("blocked") or row["status"] == "do_not_use_for_production") or "trial" in row["access"] or "closed" in row["access"] or row["id"] in {"tennis_data_uk", "flashscore_internal"} for row in rows)
    for row in rows:
        assert row["next"]
        assert row["type"] in {"data_source", "market_source", "discovery_aggregator", "historical_corpus", "data_scraper", "market_and_results_archive"}
    print("SOURCE_DISCOVERY_FRONTIER=PASS")
    print(f"FRONTIER_COUNT={len(rows)}")
    print(f"BLOCKED_COUNT={len(blocked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
