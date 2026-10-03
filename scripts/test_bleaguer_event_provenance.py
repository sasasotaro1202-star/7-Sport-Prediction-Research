#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import sqlite3
import tempfile
from pathlib import Path

from src.bleaguer_git_provenance import (
    apply,
    find_first_summary_provenance,
    stable_bleaguer_event_id,
    summary_row_fingerprint,
    summary_targets_from_bytes,
)


FIELDS = ["ScheduleKey", "TeamId", "Date", "PTS", "TR", "AS", "ST", "BS", "TO",
          "F2GM", "F2GA", "F3GM", "F3GA", "FTM", "FTA"]


def csv_bytes(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def row(schedule, team, pts):
    return {
        "ScheduleKey": schedule,
        "TeamId": team,
        "Date": "2020-01-01",
        "PTS": str(pts),
        "TR": "10",
        "AS": "5",
        "ST": "2",
        "BS": "1",
        "TO": "3",
        "F2GM": "20",
        "F2GA": "40",
        "F3GM": "8",
        "F3GA": "20",
        "FTM": "10",
        "FTA": "12",
    }


def main():
    # Numeric rendering differences must not change the feature-value fingerprint.
    assert summary_row_fingerprint(row("100", "A", "88")) == summary_row_fingerprint(
        {**row("100", "A", "88"), "PTS": "88.0"}
    )

    current_rows = [
        row("100", "A", "88"),
        row("100", "B", "77"),
        row("101", "A", "91"),
        row("101", "B", "80"),
    ]
    current = csv_bytes(current_rows)
    targets = summary_targets_from_bytes(current)
    assert set(targets) == {"100", "101"}

    # Event 100 is exact in the first revision.
    # Event 101 has one exact row in each revision, but never both rows together.
    # It must therefore remain unresolved (fail-closed).
    rev1 = csv_bytes([
        row("100", "A", "88"),
        row("100", "B", "77"),
        row("101", "A", "91"),
        row("101", "B", "79"),
    ])
    rev2 = csv_bytes([
        row("100", "A", "88"),
        row("100", "B", "77"),
        row("101", "A", "91"),
        row("101", "B", "80"),
    ])

    out = find_first_summary_provenance(
        current,
        [
            ("commit-new", "2026-01-02T00:00:00+00:00", rev2),
            ("commit-old", "2026-01-01T00:00:00+00:00", rev1),
        ],
    )

    assert out["100"]["provenance_commit_sha"] == "commit-old"
    # The supplied revisions are not a simultaneous exact proof for event 101
    # until rev2; rev2 contains both exact rows, so it should resolve there.
    assert out["101"]["provenance_commit_sha"] == "commit-new"

    # Explicitly confirm that two rows from separate revisions are never merged.
    rev_a = csv_bytes([row("200", "A", "70"), row("200", "B", "69")])
    rev_b = csv_bytes([row("200", "A", "71"), row("200", "B", "68")])
    # Different current target values ensure no accidental partial-row matching.
    current_200 = csv_bytes([row("200", "A", "71"), row("200", "B", "69")])
    out_200 = find_first_summary_provenance(
        current_200,
        [
            ("rev-a", "2026-01-01T00:00:00+00:00", rev_a),
            ("rev-b", "2026-01-02T00:00:00+00:00", rev_b),
        ],
    )
    assert "200" not in out_200

    # Event-level version evidence must remain outside strict PIT:
    # source_snapshot has no source_available_at_utc and stays
    # VERSION_EXACT_PUBLICATION_UNPROVEN; match_stats keeps the current-source
    # URL until independent public-availability evidence exists.
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "test.sqlite"
        con = sqlite3.connect(db)
        con.executescript(
            """
            CREATE TABLE source_snapshot(
                snapshot_id TEXT PRIMARY KEY, sport TEXT, source TEXT,
                source_url TEXT, retrieved_at_utc TEXT,
                source_available_at_utc TEXT, event_time_utc TEXT,
                content_hash TEXT, payload_path TEXT, parser_version TEXT,
                availability_status TEXT, provenance_json TEXT
            );
            CREATE TABLE event(event_id TEXT PRIMARY KEY, sport TEXT, event_time_utc TEXT);
            CREATE TABLE match_stats(
                stat_id TEXT PRIMARY KEY, event_id TEXT, sport TEXT,
                source TEXT, source_url TEXT
            );
            """
        )
        eid = stable_bleaguer_event_id("300")
        current_url = "https://raw.githubusercontent.com/rintaromasuda/bleaguer/master/inst/extdata/games_summary_202122.csv"
        pinned_url = "https://raw.githubusercontent.com/rintaromasuda/bleaguer/abc123/inst/extdata/games_summary_202122.csv"
        con.execute("INSERT INTO event VALUES(?,?,?)", (eid, "basketball", "2022-01-01T00:00:00+00:00"))
        con.execute(
            "INSERT INTO match_stats VALUES(?,?,?,?,?)",
            ("stat-1", eid, "basketball", "bleaguer-github", current_url),
        )
        con.commit()
        con.close()

        proof = [{
            "path": "inst/extdata/games_summary_202122.csv",
            "status": "VERSION_EXACT_PUBLICATION_UNPROVEN",
            "checked_at_utc": "2026-10-04T00:00:00+00:00",
            "event_provenance": [{
                "schedule_key": "300",
                "provenance_commit_sha": "abc123",
                "commit_timestamp_utc": "2021-12-01T00:00:00+00:00",
                "publication_status": "UNPROVEN",
                "content_hash": "hash-300",
                "matched_team_ids": ["A", "B"],
                "pinned_source_url": pinned_url,
            }],
        }]
        result = apply(db, proof)
        assert result["event_version_provenance"] == 1
        con = sqlite3.connect(db)
        snap = con.execute(
            "SELECT source_url,source_available_at_utc,event_time_utc,availability_status,provenance_json "
            "FROM source_snapshot WHERE sport='basketball'"
        ).fetchone()
        repointed = con.execute("SELECT source_url FROM match_stats WHERE stat_id='stat-1'").fetchone()
        con.close()
        assert snap[0:4] == (pinned_url, None, None, "VERSION_EXACT_PUBLICATION_UNPROVEN")
        assert '"publication_status": "UNPROVEN"' in snap[4]
        assert repointed == (current_url,)

    print("BLEAGUER_EVENT_PROVENANCE=PASS")


if __name__ == "__main__":
    main()
