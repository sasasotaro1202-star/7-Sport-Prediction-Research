from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import src.international_context as ctx
from src.storage.db_v45 import SCHEMA, _migrate


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sports.sqlite"
        con = sqlite3.connect(db)
        con.executescript(SCHEMA)
        _migrate(con)

        event_time = "2026-09-20T12:00:00+00:00"
        cutoff = "2026-09-20T11:00:00+00:00"
        con.execute(
            "INSERT INTO event(event_id,sport,competition_id,stage,round,event_time_utc,status,quality_status) VALUES(?,?,?,?,?,?,?,?)",
            ("e1", "basketball", "FIBA World Cup", "Final", "Final", event_time, "scheduled", "VERIFIED"),
        )
        con.execute(
            "INSERT INTO event_participant(event_id,participant_id,side,source,source_url,effective_at_utc,quality_status) VALUES(?,?,?,?,?,?,?)",
            ("e1", "p1", "A", "espn", "https://site.api.espn.com/event", cutoff, "EXACT"),
        )
        con.execute(
            "INSERT INTO event_participant(event_id,participant_id,side,source,source_url,effective_at_utc,quality_status) VALUES(?,?,?,?,?,?,?)",
            ("e1", "p2", "B", "espn", "https://site.api.espn.com/event", cutoff, "EXACT"),
        )
        con.execute(
            """INSERT INTO source_snapshot(
               snapshot_id,sport,source,source_url,retrieved_at_utc,source_available_at_utc,
               event_time_utc,content_hash,payload_path,parser_version,availability_status,provenance_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("s1", "basketball", "espn", "https://site.api.espn.com/event",
             "2026-09-20T09:00:00+00:00", "2026-09-20T09:00:00+00:00",
             event_time, "hash", "raw/event.json", "test", "EXACT", "{}"),
        )
        con.commit()
        con.close()

        original = ctx.DB
        ctx.DB = db
        try:
            result = ctx.rebuild()
        finally:
            ctx.DB = original

        con = sqlite3.connect(db)
        rows = con.execute(
            "SELECT stat_name,value_num,quality_status,effective_at_utc FROM match_stats WHERE sport='basketball' ORDER BY stat_name"
        ).fetchall()
        con.close()

        assert result["exact_rows"] == 8, result
        assert len(rows) == 8, rows
        names = {r[0] for r in rows}
        assert names == set(ctx.CONTEXT_STATS)
        assert all(r[2] == "EXACT" for r in rows)
        assert all(r[3] == cutoff for r in rows)
        assert all(r[0] == "ctx_international_flag" or r[1] is not None for r in rows)
        print("INTERNATIONAL_CONTEXT_PIT=PASS")
        print("EXACT_CONTEXT_ROWS", len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
