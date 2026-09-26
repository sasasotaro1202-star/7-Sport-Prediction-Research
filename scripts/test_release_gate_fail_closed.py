"""Regression tests for the production release gate's fail-closed exit semantics."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import src.production_release_gate as gate


def main() -> int:
    with TemporaryDirectory() as tmp:
        out = Path(tmp) / "release_gate.json"
        original = gate.OUT
        gate.OUT = out
        try:
            blocked = {
                "status": "BLOCKED",
                "publish": False,
                "fatal": ["synthetic_gate_failure"],
                "deferred_sports": {},
                "coverage": {},
                "coverage_warnings": [],
                "publishable_artifacts": [],
            }
            rc_blocked = gate._write(blocked)
            assert rc_blocked == 1, rc_blocked
            saved_blocked = json.loads(out.read_text(encoding="utf-8"))
            assert saved_blocked["status"] == "BLOCKED"
            assert saved_blocked["publish"] is False
            assert saved_blocked["fatal"] == ["synthetic_gate_failure"]
            assert saved_blocked["publishable_artifacts"] == []

            ready = {
                "status": "BLOCKED",
                "publish": False,
                "fatal": [],
                "deferred_sports": {"tennis": "DEFERRED_PIT"},
                "coverage": {},
                "coverage_warnings": [],
                "publishable_artifacts": ["models/example.joblib"],
            }
            rc_ready = gate._write(ready)
            assert rc_ready == 0, rc_ready
            saved_ready = json.loads(out.read_text(encoding="utf-8"))
            assert saved_ready["status"] == "READY_WITH_EXPLICIT_DEFERRED_SPORTS"
            assert saved_ready["publish"] is True
            assert saved_ready["publishable_artifacts"] == ["models/example.joblib"]
        finally:
            gate.OUT = original

    print("RELEASE_GATE_FAIL_CLOSED=PASS")
    print("BLOCKED_EXIT_CODE=1")
    print("READY_EXIT_CODE=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
