from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

from src.storage.db_v45 import SCHEMA

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bleague_public_availability_shadow_audit",
    ROOT / "scripts/bleague_public_availability_shadow_audit.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

target_team_ids = MODULE.target_team_ids


def main() -> None:
    # Use the canonical production schema rather than a reduced test schema.
    # This catches queries against columns that do not exist in event_participant.
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)

    columns = {row[1] for row in con.execute("PRAGMA table_info(event_participant)")}
    assert "sport" not in columns

    event_id = "schema-contract-event"
    con.executemany(
        """
        INSERT INTO event_participant(
            event_id, participant_id, team_id, side, role, source,
            source_url, quality_status
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        [
            (event_id, "participant-a", "TEAM-A", "A", "match", "test", "https://example.invalid/a", "UNVERIFIABLE"),
            (event_id, "participant-b", "TEAM-B", "B", "match", "test", "https://example.invalid/b", "UNVERIFIABLE"),
        ],
    )
    con.commit()

    assert target_team_ids(con, event_id) == {"TEAM-A", "TEAM-B"}
    con.close()

    print("BLEAGUE_PUBLIC_AVAILABILITY_SHADOW_AUDIT_SCHEMA=PASS")


if __name__ == "__main__":
    main()
