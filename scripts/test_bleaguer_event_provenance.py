#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import sqlite3
import tempfile
from pathlib import Path

import src.bleaguer_git_provenance as provenance

from src.bleaguer_git_provenance import (
    apply,
    find_first_summary_provenance,
    secondary_publication_bound,
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

    bound = secondary_publication_bound(
        "inst/extdata/games_summary_202021.csv",
        "42c621a5437228a4d5a796f62116bee5cc44dce2",
    )
    assert bound is not None
    assert bound["public_availability_bound_utc"] == "2021-04-19T23:59:59+00:00"
    assert secondary_publication_bound(
        "inst/extdata/games_202021.csv",
        "42c621a5437228a4d5a796f62116bee5cc44dce2",
    ) is None

    # A later revision with explicit publication evidence must beat an earlier
    # exact-but-unproven revision for the same event.
    original_bound = provenance.secondary_publication_bound
    try:
        provenance.secondary_publication_bound = (
            lambda path, sha: (
                {
                    "source_url": "https://example.invalid/evidence",
                    "published_on": "2021-04-19",
                    "public_availability_bound_utc": "2021-04-19T23:59:59+00:00",
                    "evidence_level": "SECONDARY_INDEPENDENT_REFERENCE",
                    "claim_supported": "synthetic",
                    "revision_sha": sha,
                }
                if sha == "commit-new" else None
            )
        )
        preferred = find_first_summary_provenance(
            current,
            [
                ("commit-new", "2026-01-02T00:00:00+00:00", current),
                ("commit-old", "2026-01-01T00:00:00+00:00", current),
            ],
            path="inst/extdata/games_summary_202021.csv",
        )
        assert preferred["100"]["provenance_commit_sha"] == "commit-new"
        assert preferred["100"]["publication_status"] == "PROVEN_BY_SECONDARY_DATE_BOUND"
    finally:
        provenance.secondary_publication_bound = original_bound

    # Invalid chronology in the evidence registry must fail closed.
    original_root = provenance.ROOT
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            evidence_path = root / "results/research/bleague_public_availability_evidence.json"
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(
                '{"evidence":[{"revision_evidence":{"file":"inst/extdata/games_summary_202021.csv",'
                '"exact_revision_sha":"bad-sha",'
                '"revision_commit_timestamp_utc":"2021-05-01T00:00:00Z",'
                '"next_file_touch_timestamp_utc":"2021-05-10T00:00:00Z",'
                '"no_intervening_file_touch_between_revision_and_independent_publication":true,'
                '"public_availability_bound":{"precision":"DATE_ONLY","latest_safe_utc":"2021-04-19T23:59:59Z"}}}]}',
                encoding="utf-8",
            )
            provenance.ROOT = root
            assert provenance.secondary_publication_bound(
                "inst/extdata/games_summary_202021.csv",
                "bad-sha",
            ) is None
    finally:
        provenance.ROOT = original_root

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
        proof[0]["public_availability_bound_utc"] = "2021-12-02T23:59:59+00:00"
        proof[0]["publication_status"] = "PROVEN_BY_SECONDARY_DATE_BOUND"
        proof[0]["publication_evidence"] = {"source_url": "https://example.invalid/evidence"}
        proof[0]["repository"] = "rintaromasuda/bleaguer"
        proof[0]["branch"] = "master"
        result = apply(db, proof)
        assert result["event_version_provenance"] == 1
        con = sqlite3.connect(db)
        snap = con.execute(
            "SELECT source_url,source_available_at_utc,event_time_utc,availability_status,provenance_json "
            "FROM source_snapshot WHERE sport='basketball'"
        ).fetchone()
        repointed = con.execute("SELECT source_url FROM match_stats WHERE stat_id='stat-1'").fetchone()
        con.close()
        assert snap[0:4] == (pinned_url, "2021-12-02T23:59:59+00:00", None, "EXACT")
        assert '"publication_status": "PROVEN_BY_SECONDARY_DATE_BOUND"' in snap[4]
        assert repointed == (pinned_url,)

    # Without an explicit publication bound, version evidence remains
    # outside strict PIT and must not rewrite source timing.
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "unproven.sqlite"
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
        eid = stable_bleaguer_event_id("301")
        current_url = "https://raw.githubusercontent.com/rintaromasuda/bleaguer/master/inst/extdata/games_summary_202122.csv"
        pinned_url = "https://raw.githubusercontent.com/rintaromasuda/bleaguer/abc123/inst/extdata/games_summary_202122.csv"
        con.execute("INSERT INTO event VALUES(?,?,?)", (eid, "basketball", "2022-01-02T00:00:00+00:00"))
        con.execute("INSERT INTO match_stats VALUES(?,?,?,?,?)", ("stat-2", eid, "basketball", "bleaguer-github", current_url))
        con.commit()
        con.close()
        proof = [{
            "path": "inst/extdata/games_summary_202122.csv",
            "status": "VERSION_EXACT_PUBLICATION_UNPROVEN",
            "repository": "rintaromasuda/bleaguer",
            "branch": "master",
            "event_provenance": [{
                "schedule_key": "301",
                "provenance_commit_sha": "abc123",
                "commit_timestamp_utc": "2021-12-01T00:00:00+00:00",
                "publication_status": "UNPROVEN",
                "content_hash": "hash-301",
                "matched_team_ids": ["A", "B"],
                "pinned_source_url": pinned_url
            }]
        }]
        result = apply(db, proof)
        assert result["event_version_provenance"] == 1
        con = sqlite3.connect(db)
        snap = con.execute(
            "SELECT source_available_at_utc,event_time_utc,availability_status FROM source_snapshot WHERE sport='basketball'"
        ).fetchone()
        repointed = con.execute("SELECT source_url FROM match_stats WHERE stat_id='stat-2'").fetchone()
        con.close()
        assert snap == (None, None, "VERSION_EXACT_PUBLICATION_UNPROVEN")
        assert repointed == (current_url,)

    print("BLEAGUER_EVENT_PROVENANCE=PASS")


if __name__ == "__main__":
    main()
