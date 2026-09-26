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
    blocked = {row["id"]: row["status"] for row in rows if row["status"] == "blocked"}
    assert "pinnapi" in blocked
    assert "pinnwire" in blocked
    assert all(row["status"] != "blocked" or "trial" in row["access"] or "closed" in row["access"] for row in rows)
    for row in rows:
        assert row["next"]
        assert row["type"] in {"data_source", "market_source", "discovery_aggregator"}
    print("SOURCE_DISCOVERY_FRONTIER=PASS")
    print(f"FRONTIER_COUNT={len(rows)}")
    print(f"BLOCKED_COUNT={len(blocked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
