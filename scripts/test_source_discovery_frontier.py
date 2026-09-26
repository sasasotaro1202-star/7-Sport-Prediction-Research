from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTIER = ROOT / "config" / "SOURCE_DISCOVERY_FRONTIER_9.json"

BLOCKED_MARKERS = (
    "trial",
    "closed",
    "not_available",
    "restricted",
    "private",
    "internal",
    "development_key",
)


def main() -> int:
    cfg = json.loads(FRONTIER.read_text(encoding="utf-8"))
    policy = cfg["policy"]
    assert policy["free_only"] is True
    assert policy["no_trial_auto_use"] is True
    assert policy["no_billing_risk"] is True

    rows = cfg["frontier"]
    assert len(rows) >= 10
    ids = {row["id"] for row in rows}
    for required in {"thesportsdb", "espn_public", "odds_api_io", "sofascore"}:
        assert required in ids

    blocked = {
        row["id"]: row["status"]
        for row in rows
        if row["status"].startswith("blocked") or row["status"] == "do_not_use_for_production"
    }
    for required in {"pinnapi", "pinnwire", "tennis_data_uk"}:
        assert required in blocked

    for row in rows:
        status = row["status"]
        access = str(row["access"]).lower()
        is_blocked = status.startswith("blocked") or status == "do_not_use_for_production"
        if is_blocked:
            assert any(marker in access for marker in BLOCKED_MARKERS), (
                f"blocked frontier row lacks an explicit access reason: {row['id']}"
            )
        assert row["next"]
        assert row["type"] in {
            "data_source",
            "market_source",
            "discovery_aggregator",
            "historical_corpus",
            "data_scraper",
            "market_and_results_archive",
            "external_forecast",
            "entity_context_source",
        }

    print("SOURCE_DISCOVERY_FRONTIER=PASS")
    print(f"FRONTIER_COUNT={len(rows)}")
    print(f"BLOCKED_COUNT={len(blocked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
