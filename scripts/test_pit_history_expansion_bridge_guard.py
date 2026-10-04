from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from src.pit_history_expansion_guard import inspect_bridge


def _db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        """CREATE TABLE source_snapshot(
            snapshot_id TEXT PRIMARY KEY,
            sport TEXT,
            source TEXT,
            source_url TEXT,
            retrieved_at_utc TEXT,
            source_available_at_utc TEXT,
            content_hash TEXT,
            availability_status TEXT,
            provenance_json TEXT
        )"""
    )
    con.execute(
        """CREATE TABLE match_stats(
            stat_id TEXT PRIMARY KEY,
            event_id TEXT,
            participant_id TEXT,
            team_id TEXT,
            sport TEXT,
            observed_at_utc TEXT,
            effective_at_utc TEXT,
            stat_name TEXT,
            value_num REAL,
            source TEXT,
            source_url TEXT,
            quality_status TEXT
        )"""
    )
    con.commit()
    con.close()


def _registry(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "status": "RESEARCH_EVIDENCE_ONLY",
        "strict_pit_usable": False,
        "revision_evidence": {
            "file": "inst/extdata/games_summary_202021.csv",
            "revision_sha": "revision-sha",
            "public_availability_bound": {
                "latest_safe_utc": "2021-04-19T23:59:59+00:00",
            },
        },
    }), encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = root / "db.sqlite"
        evidence = root / "evidence.json"
        _db(db)
        _registry(evidence)

        blocked = inspect_bridge(db, "basketball", evidence)
        assert blocked["status"] == "BLOCKED"
        assert blocked["observed"]["exact_master_summary_snapshots"] == 0

        con = sqlite3.connect(db)
        marker = "PROVEN_BY_SECONDARY_DATE_BOUND"
        provenance = json.dumps({"publication_status": marker})
        con.execute(
            """INSERT INTO source_snapshot VALUES(?,?,?,?,?,?,?,?,?)""",
            ("master", "basketball", "bleaguer-github",
             "https://raw.githubusercontent.com/rintaromasuda/bleaguer/master/inst/extdata/games_summary_202021.csv",
             "2026-10-04T00:00:00+00:00", "2021-04-19T23:59:59+00:00",
             "hash", "EXACT", provenance),
        )
        con.execute(
            """INSERT INTO source_snapshot VALUES(?,?,?,?,?,?,?,?,?)""",
            ("pinned", "basketball", "bleaguer-github",
             "https://raw.githubusercontent.com/rintaromasuda/bleaguer/revision-sha/inst/extdata/games_summary_202021.csv",
             "2026-10-04T00:00:00+00:00", "2021-04-19T23:59:59+00:00",
             "hash", "EXACT", provenance),
        )
        con.execute(
            """INSERT INTO match_stats VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("stat", "event", "p", "team", "basketball", "2026-10-04T00:00:00+00:00",
             "2021-04-21T00:00:00+00:00", "points", 1.0, "bleaguer-github",
             "https://raw.githubusercontent.com/rintaromasuda/bleaguer/revision-sha/inst/extdata/games_summary_202021.csv",
             "OK"),
        )
        con.commit()
        con.close()

        passed = inspect_bridge(db, "basketball", evidence)
        assert passed["status"] == "PASS"
        assert passed["observed"]["pinned_exact_summary_snapshots"] == 1
        assert passed["observed"]["repointed_summary_match_stats"] == 1

        unsafe = dict(json.loads(evidence.read_text(encoding="utf-8")))
        unsafe["status"] = "PRODUCTION_EVIDENCE"
        evidence.write_text(json.dumps(unsafe), encoding="utf-8")
        try:
            inspect_bridge(db, "basketball", evidence)
        except RuntimeError as exc:
            assert "unsafe_status" in str(exc)
        else:
            raise AssertionError("unsafe evidence registry was not fail-closed")

    print("PIT_HISTORY_EXPANSION_BRIDGE_GUARD=PASS")


if __name__ == "__main__":
    main()
