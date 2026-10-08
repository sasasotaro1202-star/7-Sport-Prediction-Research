#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> int:
    generated_at = os.environ.get("KEEPALIVE_GENERATED_AT", "").strip()
    base_sha = os.environ.get("KEEPALIVE_BASE_SHA", "").strip()
    if not generated_at or not base_sha:
        raise SystemExit("KEEPALIVE_INPUT_MISSING")

    target = Path("ops/automation/heartbeat.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "generated_at_utc": generated_at,
                "base_main_sha": base_sha,
                "purpose": "repository_activity_keepalive",
                "automation_only": True,
                "production_data_untouched": True,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"KEEPALIVE_MARKER_WRITTEN sha={base_sha} generated_at={generated_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
