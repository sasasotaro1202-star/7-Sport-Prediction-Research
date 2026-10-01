from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.prediction_route_observability import build_report


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="route-observability-") as tmp:
        db = Path(tmp) / "sports.sqlite"
        con = sqlite3.connect(db)
        con.execute(
            """
            CREATE TABLE forward_prediction (
                prediction_id TEXT PRIMARY KEY,
                event_id TEXT,
                sport TEXT,
                prediction_cutoff_at_utc TEXT,
                generated_at_utc TEXT,
                strategy TEXT,
                features_json TEXT,
                status TEXT
            )
            """
        )
        features_ok = {
            "routing": {
                "status": "COMPETITION_SPECIFIC_ACCEPTED",
                "competition_specific": True,
            },
            "competition_profile": {"profile_id": "basketball:competition:test"},
            "prediction_timing": {
                "target_lead_minutes": 45,
                "selection_status": "TIMING_ROUTE_ACCEPTED",
            },
            "timing_selection_status": "TIMING_ROUTE_ACCEPTED",
        }
        features_fallback = {
            "routing": {
                "status": "SPORT_INCUMBENT_FALLBACK",
                "competition_specific": False,
            },
            "competition_profile": {"profile_id": "basketball:bleague"},
            "prediction_timing": {
                "target_lead_minutes": 30,
                "selection_status": "DEFAULT_GUIDELINE",
            },
            "timing_selection_status": "DEFAULT_GUIDELINE",
        }
        con.executemany(
            """
            INSERT INTO forward_prediction
            VALUES (?,?,?,?,?,?,?,?)
            """,
            [
                (
                    "p1",
                    "e1",
                    "basketball",
                    "2026-10-01T10:00:00+00:00",
                    "2026-10-01T09:15:00+00:00",
                    "competition_specific_model",
                    json.dumps(features_ok),
                    "ACTIVE",
                ),
                (
                    "p2",
                    "e2",
                    "basketball",
                    "2026-10-01T11:00:00+00:00",
                    "2026-10-01T10:55:00+00:00",
                    "fixed_equal_weight",
                    json.dumps(features_fallback),
                    "ACTIVE",
                ),
            ],
        )
        con.commit()
        con.close()

        report = build_report(db, datetime(2026, 10, 1, tzinfo=timezone.utc))
        assert report["status"] == "PASS"
        assert report["source"]["prediction_rows"] == 2
        assert report["runtime_integrity"]["late_generated_total"] == 0
        assert report["by_router_status"]["COMPETITION_SPECIFIC_ACCEPTED"] == 1
        assert report["by_router_status"]["SPORT_INCUMBENT_FALLBACK"] == 1
        assert report["by_target_lead_minutes"]["45"] == 1
        assert report["by_target_lead_minutes"]["30"] == 1
        assert report["by_sport"]["basketball"]["competition_specific_accepted"] == 1
        assert report["by_sport"]["basketball"]["sport_incumbent_fallback"] == 1

    print("PREDICTION_ROUTE_OBSERVABILITY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
