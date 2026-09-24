from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.postmatch_review import main
from src.storage.db_v45 import SCHEMA, _migrate


def main_test():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "m.sqlite"
        out = Path(td) / "review.json"
        c = sqlite3.connect(db)
        c.executescript(SCHEMA)
        _migrate(c)
        c.execute(
            "INSERT INTO event(event_id,sport,event_time_utc,status,quality_status) VALUES(?,?,?,?,?)",
            ("e1","basketball","2026-09-24T00:00:00+00:00","COMPLETED","OK"),
        )
        c.execute(
            "INSERT INTO event_outcome(event_id,sport,outcome,outcome_status,source,observed_at_utc,quality_status) VALUES(?,?,?,?,?,?,?)",
            ("e1","basketball","B","VERIFIED","official","2026-09-24T01:00:00+00:00","OK"),
        )
        features = {
            "matchday_intelligence": {
                "evidence_counts": {
                    "availability_latest": 2,
                    "lineup_rows": 1,
                    "weather": 1,
                    "market": 1,
                    "news": 0,
                }
            }
        }
        c.execute(
            """
            INSERT INTO forward_prediction(
                prediction_id,event_id,sport,market,prediction_cutoff_at_utc,
                generated_at_utc,probability_side_a,probability_side_b,strategy,
                model_version,feature_version,features_json,feature_snapshot_hash,status,created_at_utc
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "p1","e1","basketball","winner","2026-09-23T23:00:00+00:00",
                "2026-09-23T23:05:00+00:00",0.35,0.65,"fixed_equal_weight",
                "m1","f1",json.dumps(features), "hash1","OPEN","2026-09-23T23:05:00+00:00",
            ),
        )
        c.commit()
        c.close()

        assert main(db, out) == 0
        report = json.loads(out.read_text())
        assert report["settled_now"] == 1
        assert report["scored_now"] == 1
        assert report["incorrect_now"] == 0
        c = sqlite3.connect(db)
        row = c.execute(
            "SELECT status,settled_outcome,settlement_source FROM forward_prediction WHERE prediction_id='p1'"
        ).fetchone()
        c.close()
        assert row == ("SETTLED","B","official")
        assert any("basketball|fixed_equal_weight" == k for k in report["recent_summary"])
        print("POSTMATCH_REVIEW=PASS")


if __name__ == "__main__":
    main_test()
