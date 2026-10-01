from __future__ import annotations

import hashlib
from typing import Any, Iterable


def exact_oos_window_signature(rows: Iterable[dict[str, Any]]) -> str | None:
    """Fingerprint exact chronological OOS windows, not just fold IDs.

    Missing boundaries fail closed because a fold number alone is not enough to
    reproduce which historical period was evaluated.
    """
    identities: set[tuple[int, str, str]] = set()
    for row in rows:
        try:
            fold_value = float(row.get("fold"))
        except (TypeError, ValueError):
            continue
        if not fold_value.is_integer():
            continue
        start = str(row.get("test_start") or row.get("test_start_date") or "").strip()
        end = str(row.get("test_end") or row.get("test_end_date") or "").strip()
        if not start or not end:
            return None
        identities.add((int(fold_value), start, end))
    if not identities:
        return None
    canonical = "|".join(
        f"{fold}:{start}:{end}"
        for fold, start, end in sorted(identities)
    )
    return "oos:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
