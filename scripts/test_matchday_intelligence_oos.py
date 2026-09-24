from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from src.matchday_intelligence_oos import build_matchday_intelligence
from src.storage.db_v45 import SCHEMA, _migrate


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "m.sqlite"
        c = sqlite3.connect(db)
        c.executescript(SCHEMA)
        _migrate(c)

        c.execute(
            "INSERT INTO event(event_id,sport,competition_id,event_time_utc,status,quality_status) "
            "VALUES(?,?,?,?,?,?)",
            ("e1","basketball","B","2026-09-24T12:00:00+00:00","SCHEDULED","OK"),
        )
        c.execute(
            "INSERT INTO event(event_id,sport,competition_id,event_time_utc,status,quality_status) "
            "VALUES(?,?,?,?,?,?)",
            ("prev","basketball","B","2026-09-22T12:00:00+00:00","COMPLETED","OK"),
        )
        c.execute(
            "INSERT INTO participant(participant_id,sport,participant_type,canonical_name) VALUES(?,?,?,?)",
            ("p1","basketball","PLAYER","Player One"),
        )
        c.execute(
            "INSERT INTO participant(participant_id,sport,canonical_name) VALUES(?,?,?)",
            ("p2","basketball","PLAYER","Player Two"),
        )
        c.executemany(
            "INSERT INTO event_participant(event_id,participant_id,team_id,side,lineup_status,source,effective_at_utc,quality_status) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [
                ("e1","p1","t1","A","confirmed","official","2026-09-24T10:00:00+00:00","OK"),
                ("e1","p2","t2","B","expected","official","2026-09-24T10:00:00+00:00","OK"),
                ("prev","p1","t1","A","starter","official","2026-09-22T11:00:00+00:00","OK"),
            ],
        )
        c.executemany(
            "INSERT INTO availability(availability_id,event_id,participant_id,team_id,sport,observed_at_utc,effective_at_utc,cutoff_at_utc,status,reason,source,quality_status,confidence) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("a1","e1","p1","t1","basketball","2026-09-24T10:30:00+00:00","2026-09-24T10:30:00+00:00","2026-09-24T11:00:00+00:00","active","","official","OK",0.99),
                # This later update must not leak into the 11:00 cutoff.
                ("a2","e1","p1","t1","basketball","2026-09-24T11:30:00+00:00","2026-09-24T11:30:00+00:00","2026-09-24T11:00:00+00:00","out","late","official","OK",0.99),
            ],
        )
        c.executemany(
            "INSERT INTO match_stats(stat_id,event_id,sport,observed_at_utc,effective_at_utc,stat_name,value_num,unit,source,quality_status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                ("s1","e1","basketball","2026-09-24T09:00:00+00:00","2026-09-24T09:00:00+00:00","weather.temperature",25.0,"C","weather","OK"),
                ("s2","e1","basketball","2026-09-24T09:05:00+00:00","2026-09-24T09:05:00+00:00","market.moneyline_side_a",1.8,"decimal","market","OK"),
                ("s3","e1","basketball","2026-09-24T09:10:00+00:00","2026-09-24T09:10:00+00:00","news.availability_change",1.0,"flag","news","OK"),
                ("s4","e1","basketball","2026-09-24T12:30:00+00:00", "2026-09-24T12:30:00+00:00","weather.temperature",99.0,"C","weather","OK"),
            ],
        )
        c.commit()
        c.close()

        r = build_matchday_intelligence("e1","2026-09-24T11:00:00+00:00",db)
        assert r["event_id"] == "e1"
        assert r["features"]["availability_out_side_a"] == 0
        assert r["features"]["availability_out_side_b"] == 0
        assert r["features"]["lineup_confirmed_side_a"] == 1
        assert r["features"]["weather_signal_count"] == 1
        assert r["features"]["market_signal_count"] == 1
        assert r["features"]["news_signal_count"] == 1
        assert r["rest_schedule"]["t1"]["rest_days"] == 2.0
        assert all("99.0" not in str(v) for v in r["typed_context"]["weather"].values())
        assert r["policy"].startswith("research_only;")
        print("MATCHDAY_INTELLIGENCE_OOS=PASS")


if __name__ == "__main__":
    main()
