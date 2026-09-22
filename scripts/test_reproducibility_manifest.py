from __future__ import annotations

import tempfile
from pathlib import Path

import src.reproducibility_manifest as manifest
from src.storage.db_v45 import SCHEMA


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db = root / "boxing_v45.sqlite"
        import sqlite3
        con = sqlite3.connect(db)
        con.executescript(SCHEMA)
        con.execute(
            "INSERT INTO event(event_id,sport,quality_status) VALUES(?,?,?)",
            ("boxing-test-1", "boxing", "VERIFIED"),
        )
        con.execute(
            "INSERT INTO event(event_id,sport,quality_status) VALUES(?,?,?)",
            ("rugby-test-1", "rugby", "VERIFIED"),
        )
        con.commit()
        con.close()

        old_rugby = manifest.RUGBY_DB
        old_boxing = manifest.BOXING_DB
        try:
            manifest.RUGBY_DB = root / "missing-rugby.sqlite"
            manifest.BOXING_DB = db
            counts, storage = manifest.db_counts()
            assert storage['boxing']['status'] == 'OK'
        finally:
            manifest.RUGBY_DB = old_rugby
            manifest.BOXING_DB = old_boxing

        assert counts["boxing"] == 1, counts
        assert "bout" not in counts
        print("REPRODUCIBILITY_MANIFEST_BOXING_SCHEMA=PASS")


if __name__ == "__main__":
    main()
