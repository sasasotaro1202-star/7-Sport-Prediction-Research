from __future__ import annotations

import io
import sqlite3

from src.boxing_production import ingest_history
from src.storage.db_v45 import SCHEMA


class FakeHTTP:
    def __init__(self, payload: str):
        self.payload = payload

    def get(self, url: str):
        return self.payload, "2026-09-22T00:00:00+00:00", {"ETag": '"test"'}


def main() -> int:
    csv_text = """bout_id,date,boxer_a_champion_id,boxer_a_name,boxer_b_champion_id,boxer_b_name,status,winner,method_of_victory,total_rounds,scheduled_rounds,weight_class,weight_lb,titles,location_id
1,2020-01-01,1,Alice Example,2,Bob Example,FINISHED,BOXER A,UD,12,12,Lightweight,135,,
2,2020-02-01,3,Carol Example,4,Dan Example,SCHEDULED,,,,12,Welterweight,147,,
"""
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(SCHEMA)
        report = ingest_history(con, FakeHTTP(csv_text))
        assert report["rows"] == 2
        assert report["imported_events"] == 2
        assert report["verified_outcomes"] == 1
        events = con.execute("select count(*) from event where sport='boxing'").fetchone()[0]
        outcomes = con.execute("select count(*) from event_outcome where sport='boxing' and outcome_status='VERIFIED'").fetchone()[0]
        assert events == 2
        assert outcomes == 1
        print("BOXING_INGEST_UNIT=PASS")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
