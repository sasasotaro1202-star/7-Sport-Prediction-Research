from __future__ import annotations

import csv
import io
import json
import sqlite3
import tempfile
from pathlib import Path

from src.bleague_exact_pit_bridge import materialize

SCHEMA = """
CREATE TABLE event(
  event_id TEXT PRIMARY KEY,sport TEXT NOT NULL,competition_id TEXT,
  season TEXT,stage TEXT,round TEXT,event_time_utc TEXT,event_end_time_utc TEXT,
  event_type TEXT,status TEXT,source_count INTEGER,quality_status TEXT,
  rejection_reason TEXT,created_at TEXT,updated_at TEXT
);
CREATE TABLE participant(
  participant_id TEXT PRIMARY KEY,sport TEXT NOT NULL,participant_type TEXT NOT NULL,
  canonical_name TEXT,first_seen_at TEXT,last_seen_at TEXT
);
CREATE TABLE event_participant(
  event_id TEXT NOT NULL,participant_id TEXT,team_id TEXT,side TEXT,role TEXT,
  seed REAL,lineup_status TEXT,source TEXT,source_url TEXT,effective_at_utc TEXT,
  quality_status TEXT NOT NULL,
  PRIMARY KEY(event_id,participant_id,team_id,side,role)
);
CREATE TABLE match_stats(
  stat_id TEXT PRIMARY KEY,event_id TEXT NOT NULL,participant_id TEXT,team_id TEXT,
  sport TEXT NOT NULL,observed_at_utc TEXT NOT NULL,effective_at_utc TEXT,
  stat_name TEXT NOT NULL,value_num REAL,value_text TEXT,unit TEXT,source TEXT,
  source_url TEXT,quality_status TEXT NOT NULL,confidence REAL
);
CREATE TABLE source_snapshot(
  snapshot_id TEXT PRIMARY KEY,sport TEXT,source TEXT NOT NULL,source_url TEXT,
  retrieved_at_utc TEXT NOT NULL,source_available_at_utc TEXT,event_time_utc TEXT,
  content_hash TEXT,payload_path TEXT,parser_version TEXT,availability_status TEXT NOT NULL,
  provenance_json TEXT
);
"""

def _csv(headers: list[str], rows: list[list[object]]) -> bytes:
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue().encode()

def _schedule_csv() -> bytes:
    return _csv(
        ["ScheduleKey","Season","EventId","Date","Arena","Attendance","HomeTeamId","AwayTeamId"],
        [["100","2020-21","2","2021-04-18","Test Arena","100","700","706"]],
    )

def _summary_csv() -> bytes:
    headers = [
        "ScheduleKey","TeamId","PTS","Q1","Q2","Q3","Q4","OT1","OT2","OT3","OT4",
        "F2GM","F2GA","F3GM","F3GA","FTM","FTA","OR","DR","TR","AS","TO","ST","BS",
        "F","PtsBiggestLead","PtsInPaint","PtsFastBreak","PtsSecondChance",
        "PtsFromTurnover","BiggestScoringRun","LeadChanges","TimesTied",
    ]
    base = [0] * 30
    rows = []
    for team, points in (("700",88),("706",77)):
        row = ["100",team,points] + base[:]
        row[11:17] = [30,50,8,20,10,12]
        row[19:25] = [10,5,2,3,4,0]
        rows.append(row)
    return _csv(headers, rows)

def _evidence(path: Path, revision: str = "revision-sha") -> None:
    path.write_text(json.dumps({
        "status":"RESEARCH_EVIDENCE_ONLY",
        "strict_pit_usable":False,
        "revision_evidence":{
            "file":"inst/extdata/games_summary_202021.csv",
            "revision_sha":revision,
            "public_availability_bound":{
                "latest_safe_utc":"2021-04-19T23:59:59Z"
            },
        },
    }),encoding="utf-8")


def test_canonical_event_id_accepts_bleague_dot_date() -> None:
    from src.bleaguer_git_provenance import canonical_bleaguer_event_id

    row = {
        "ScheduleKey": "5938",
        "HomeTeamId": "700",
        "AwayTeamId": "706",
        "Date": "2020.10.24",
    }
    event_id = canonical_bleaguer_event_id(
        row, "inst/extdata/games_202021.csv"
    )
    assert event_id is not None
    assert len(event_id) == 32


def main() -> None:
    test_canonical_event_id_accepts_bleague_dot_date()
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        db=root/"test.sqlite"
        evidence=root/"evidence.json"
        schedule={
            "ScheduleKey":"100","HomeTeamId":"700","AwayTeamId":"706",
            "Date":"2021-04-18",
        }
        from src.bleaguer_git_provenance import canonical_bleaguer_event_id
        event_id=canonical_bleaguer_event_id(schedule,"inst/extdata/games_202021.csv")

        con=sqlite3.connect(db)
        con.executescript(SCHEMA)
        con.execute(
            "INSERT INTO event VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id,"basketball","B.LEAGUE","2020-21",None,None,
             "2021-04-18T00:00:00+00:00",None,"match","COMPLETED",1,
             "PRESENT_NOT_PIT_VERIFIED",None,"2026-01-01","2026-01-01"),
        )
        con.executemany(
            "INSERT INTO participant VALUES(?,?,?,?,?,?)",
            [("p-a","basketball","team","700","2020-01-01","2026-01-01"),
             ("p-b","basketball","team","706","2020-01-01","2026-01-01")],
        )
        con.executemany(
            "INSERT INTO event_participant VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(event_id,"p-a","p-a","A","match",None,None,"bleaguer-github",
              "https://example/current","2021-04-18T00:00:00+00:00","UNVERIFIABLE"),
             (event_id,"p-b","p-b","B","match",None,None,"bleaguer-github",
              "https://example/current","2021-04-18T00:00:00+00:00","UNVERIFIABLE")],
        )
        con.commit()
        con.close()
        _evidence(evidence)

        responses={
            "https://raw.githubusercontent.com/rintaromasuda/bleaguer/revision-sha/inst/extdata/games_202021.csv":_schedule_csv(),
            "https://raw.githubusercontent.com/rintaromasuda/bleaguer/revision-sha/inst/extdata/games_summary_202021.csv":_summary_csv(),
        }

        report=materialize(
            db,evidence,http_get=lambda url:responses[url],
            observed_at_utc="2026-10-04T00:00:00+00:00",
        )
        assert report["status"]=="APPLIED"
        assert report["events_applied"]==1
        assert report["stats_applied"]==24

        con=sqlite3.connect(db)
        rows=con.execute(
            "SELECT participant_id,stat_name,value_num,source_url,quality_status "
            "FROM match_stats ORDER BY participant_id,stat_name"
        ).fetchall()
        snapshot=con.execute(
            "SELECT source_url,source_available_at_utc,availability_status,provenance_json "
            "FROM source_snapshot"
        ).fetchone()
        con.close()
        assert len(rows)==24
        assert all(
            "/revision-sha/inst/extdata/games_summary_202021.csv" in row[3]
            for row in rows
        )
        assert all(row[4]=="EXACT" for row in rows)
        assert snapshot[1]=="2021-04-19T23:59:59+00:00"
        assert snapshot[2]=="EXACT"
        assert '"publication_status": "PROVEN_BY_SECONDARY_DATE_BOUND"' in snapshot[3]
        assert '"source_url_pinned_to_commit": true' in snapshot[3]

        con=sqlite3.connect(db)
        con.execute("DELETE FROM match_stats")
        con.execute("DELETE FROM source_snapshot")
        con.execute("DELETE FROM event_participant")
        con.execute("DELETE FROM event")
        con.commit()
        con.close()
        try:
            materialize(
                db,evidence,http_get=lambda url:responses[url],
                observed_at_utc="2026-10-04T00:00:00+00:00",
            )
        except RuntimeError as exc:
            assert str(exc).startswith("NO_EXACT_PIT_ROWS_MATERIALIZED")
        else:
            raise AssertionError("missing canonical event did not block")
        con=sqlite3.connect(db)
        assert con.execute("SELECT COUNT(*) FROM source_snapshot").fetchone()[0]==0
        con.close()

        unsafe=json.loads(evidence.read_text(encoding="utf-8"))
        unsafe["status"]="PRODUCTION_EVIDENCE"
        evidence.write_text(json.dumps(unsafe),encoding="utf-8")
        try:
            materialize(
                db,evidence,
                http_get=lambda _: (_ for _ in ()).throw(
                    AssertionError("must not fetch")
                ),
            )
        except RuntimeError as exc:
            assert "unsafe_status" in str(exc)
        else:
            raise AssertionError("unsafe evidence was accepted")

    print("BLEAGUE_EXACT_PIT_MATERIALIZATION=PASS")

if __name__ == "__main__":
    main()
