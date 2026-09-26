#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / "config" / "ACTIVE_SCOPE_9_SPORTS.json"
WORKFLOW = ROOT / ".github" / "workflows" / "all_sport_research.yml"


def main() -> int:
    cfg = json.loads(SCOPE.read_text(encoding="utf-8"))
    active = [
        str(sport)
        for sport, entries in (cfg.get("active_scope") or {}).items()
        if isinstance(entries, list)
        and any(
            isinstance(entry, dict)
            and str(entry.get("status", "")).upper() == "TARGET"
            for entry in entries
        )
    ]
    deferred = set((cfg.get("deferred_scope") or {}).keys())

    assert active, "active scope must contain at least one TARGET sport"
    assert len(active) == len(set(active)), "active scope must be unique"
    assert not (set(active) & deferred), "TARGET and DEFERRED scopes must be disjoint"

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "config/ACTIVE_SCOPE_9_SPORTS.json" in workflow
    assert "Resolve TARGET sports from canonical scope" in workflow
    assert "fromJSON(needs.scope.outputs.sports)" in workflow
    assert "sport:" in workflow
    # The execution matrix must not reintroduce a separate hard-coded sport list.
    matrix_pos = workflow.index("matrix:")
    tail = workflow[matrix_pos : matrix_pos + 260]
    assert "fromJSON(needs.scope.outputs.sports)" in tail

    print("ACTIVE_SCOPE_WORKFLOW=PASS")
    print("ACTIVE_SPORTS=" + ",".join(active))
    print("DEFERRED_SPORTS=" + ",".join(sorted(deferred)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
