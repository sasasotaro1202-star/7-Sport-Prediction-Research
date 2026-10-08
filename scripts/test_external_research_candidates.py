#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config/external_research_candidates.json"


def main() -> int:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert data["status"] == "RESEARCH_REGISTRY_ONLY"
    assert data["production_dependency"] is False
    assert data["auto_promotion"] is False

    ids = []
    for candidate in data["candidates"]:
        ids.append(candidate["id"])
        assert candidate["tier"] == "A"
        assert candidate["status"] == "PROMOTION_CANDIDATE"
        assert candidate["scope"] == "research_engineering_only"
        assert candidate["integration_role"]
        assert candidate["forbidden"]
        assert candidate["gate"]
        assert candidate["license"] in {"MIT", "Apache-2.0"}

    assert len(ids) == len(set(ids))
    assert {c["repository"] for c in data["candidates"]} == {
        "mattpocock/skills",
        "Fission-AI/OpenSpec",
        "Graphify-Labs/graphify",
    }

    # Keep external OSS candidates out of the production dependency manifest.
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for forbidden in ("mattpocock", "OpenSpec", "graphify", "agent-reach", "firecrawl"):
        assert forbidden.lower() not in requirements.lower()

    print("EXTERNAL_OSS_RESEARCH_REGISTRY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
