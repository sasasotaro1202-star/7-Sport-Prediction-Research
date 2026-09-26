from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "SPORT_DATA_SOURCES_9.json"


def load_registry() -> dict[str, Any]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def source_candidates(
    sport: str,
    *,
    research: bool = True,
    free_only: bool = True,
) -> list[dict[str, Any]]:
    cfg = load_registry()
    rows = cfg["sports"].get(sport, [])
    out = []
    for row in rows:
        if free_only and not row.get("free", False):
            continue
        if not research and row.get("class") != "primary":
            continue
        out.append(dict(row))
    return out


def pit_status(
    *,
    available_at: str | None,
    prediction_time: str,
) -> str:
    """Fail closed when historical availability cannot be established."""
    if not available_at:
        return "UNKNOWN_FAIL_CLOSED"
    try:
        a = _parse_utc(available_at)
        p = _parse_utc(prediction_time)
    except ValueError:
        return "UNKNOWN_FAIL_CLOSED"
    return "PASS" if a <= p else "FAIL"


def _parse_utc(value: str) -> datetime:
    s = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
