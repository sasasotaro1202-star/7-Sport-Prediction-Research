from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bleague_public_availability_shadow_audit",
    ROOT / "scripts/bleague_public_availability_shadow_audit.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

DB_STAT_NAMES = MODULE.DB_STAT_NAMES
audit_db = MODULE.audit_db
stable_bleaguer_event_id = MODULE.stable_bleaguer_event_id


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "shadow.sqlite"
        con = sqlite3.connect(db)
        con.executescript(
            """
            CREATE TABLE event(
                event_id TEXT PRIMARY KEY,
                sport TEXT,
                event_time_utc TEXT,
                competition_id TEXT,
                season TEXT,
                stage TEXT,
                round TEXT,
                event_type TEXT,
                status TEXT
            );
            CREATE TABLE event_participant(
                event_id TEXT,
                sport TEXT,
                side TEXT,
                participant_id TEXT,
                team_id TEXT
            );
            CREATE TABLE match_stats(
                stat_id TEXT PRIMARY KEY,
                event_id TEXT,
                participant_id TEXT,
                stat_name TEXT,
                value_num REAL,
                effective_at_utc TEXT,
                quality_status TEXT,
                source TEXT,
                source_url TEXT
            );
            """
        )

        feature_key = "100"
        target_key = "200"
        feature_id = stable_bleaguer_event_id(feature_key)
        target_id = stable_bleaguer_event_id(target_key)
        feature_time = "2021-04-10T00:00:00+00:00"
        target_time = "2021-04-20T02:00:00+00:00"

        for event_id, event_time in ((feature_id, feature_time), (target_id, target_time)):
            con.execute(
                "INSERT INTO event VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    "basketball",
                    event_time,
                    "B.LEAGUE",
                    "2020-21",
                    "league",
                    "regular",
                    "match",
                    "COMPLETED",
                ),
            )
            con.executemany(
                "INSERT INTO event_participant VALUES(?,?,?,?,?)",
                [
                    (event_id, "basketball", "A", f"{event_id}-A", "TEAM-A"),
                    (event_id, "basketball", "B", f"{event_id}-B", "TEAM-B"),
                ],
            )

        values_a = {name: float(i + 1) for i, name in enumerate(DB_STAT_NAMES)}
        values_b = {name: float(i + 101) for i, name in enumerate(DB_STAT_NAMES)}

        rows = []
        for participant_id, values in (
            (f"{feature_id}-A", values_a),
            (f"{feature_id}-B", values_b),
        ):
            for stat_name, value in values.items():
                rows.append(
                    (
                        f"{participant_id}-{stat_name}",
                        feature_id,
                        participant_id,
                        stat_name,
                        value,
                        feature_time,
                        "UNVERIFIABLE",
                        "bleaguer-github",
                        "https://raw.githubusercontent.com/rintaromasuda/bleaguer/master/inst/extdata/games_summary_202021.csv",
                    )
                )
        con.executemany(
            "INSERT INTO match_stats VALUES(?,?,?,?,?,?,?,?,?)",
            rows,
        )
        con.commit()

        exact_rows = {
            feature_key: {
                "RAW-TEAM-A": {field: value for field, value in zip(
                    ("PTS", "TR", "AS", "ST", "BS", "TO", "F2GM", "F2GA", "F3GM", "F3GA", "FTM", "FTA"),
                    values_a.values(),
                )},
                "RAW-TEAM-B": {field: value for field, value in zip(
                    ("PTS", "TR", "AS", "ST", "BS", "TO", "F2GM", "F2GA", "F3GM", "F3GA", "FTM", "FTA"),
                    values_b.values(),
                )},
            }
        }

        report = audit_db(
            con,
            exact_rows=exact_rows,
            matched_schedule_keys={feature_key},
            bound=datetime(2021, 4, 19, 23, 59, 59, tzinfo=timezone.utc),
        )
        con.close()

        assert report["matched_events_present_in_db"] == 1
        assert report["exact_feature_vector_events"] == 1
        assert report["exact_feature_stat_rows"] == 24
        assert report["identity_scope"] == "canonical_schedule_key_event_identity; two-team vector matching is side-agnostic"

        # Both fixture events are B.LEAGUE rows, so the raw candidate total
        # includes the historical feature event as well as the target event.
        # Only the target event has a T-60 cutoff at or after the bound.
        assert report["candidate_target_events_total"] == 2
        assert report["candidate_target_events_cutoff_at_or_after_bound"] == 1
        assert report["candidate_targets_with_any_exact_history"] == 1
        assert report["candidate_targets_with_both_team_exact_history"] == 1
        assert report["candidate_prior_history_observations"] == 1

    print("BLEAGUE_PUBLIC_AVAILABILITY_SHADOW_AUDIT_UNIT=PASS")


if __name__ == "__main__":
    main()
