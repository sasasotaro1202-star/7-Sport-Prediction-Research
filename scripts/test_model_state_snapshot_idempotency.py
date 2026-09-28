from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ModelStateSnapshotIdempotencyTests(unittest.TestCase):
    def test_research_code_uses_idempotent_snapshot_write(self):
        text = (ROOT / "src" / "research_cycle_strict.py").read_text(encoding="utf-8")
        self.assertIn(
            "INSERT OR REPLACE INTO model_state_snapshot",
            text,
        )
        self.assertNotIn(
            "INSERT INTO model_state_snapshot",
            text.replace("INSERT OR REPLACE INTO model_state_snapshot", ""),
        )

    def test_sqlite_upsert_keeps_one_snapshot(self):
        with sqlite3.connect(":memory:") as con:
            con.execute(
                """
                CREATE TABLE model_state_snapshot (
                    snapshot_id TEXT PRIMARY KEY,
                    sport TEXT,
                    market TEXT,
                    as_of_utc TEXT,
                    model_version TEXT
                )
                """
            )
            sql = """
                INSERT OR REPLACE INTO model_state_snapshot
                (snapshot_id, sport, market, as_of_utc, model_version)
                VALUES (?, ?, ?, ?, ?)
            """
            row = ("same", "volleyball", "winner", "2026-09-28T08:00:00Z", "v1")
            con.execute(sql, row)
            con.execute(sql, (*row[:3], "2026-09-28T08:05:00Z", "v2"))
            count = con.execute(
                "SELECT COUNT(*) FROM model_state_snapshot WHERE snapshot_id='same'"
            ).fetchone()[0]
            self.assertEqual(count, 1)
            version = con.execute(
                "SELECT model_version FROM model_state_snapshot WHERE snapshot_id='same'"
            ).fetchone()[0]
            self.assertEqual(version, "v2")


if __name__ == "__main__":
    unittest.main()
