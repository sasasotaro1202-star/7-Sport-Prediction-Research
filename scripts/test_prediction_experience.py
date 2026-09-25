from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src import prediction_experience as pe


class PredictionExperienceTests(unittest.TestCase):
    def test_binary_score_is_proper_and_identifies_wrong_overconfidence(self):
        pred = {
            "probability_side_a": 0.02,
            "probability_side_b": 0.98,
            "confidence": "HIGH",
            "situation": {"quality": {"evidence_count": 4, "conflict_rate": 0.05}},
            "strategy": "test",
        }
        row = pe._score_binary(pred, "A")
        self.assertIsNotNone(row)
        self.assertFalse(row["correct"])
        self.assertEqual(row["experience_class"], "WRONG_OVERCONFIDENT")
        self.assertAlmostEqual(row["brier"], 0.9604, places=6)

    def test_f1_score_handles_missing_winner_as_surprise(self):
        pred = {
            "drivers": [
                {"participant_id": "a", "probability": 0.7},
                {"participant_id": "b", "probability": 0.3},
            ],
            "confidence": "HIGH",
            "strategy": "safe_prior_multiclass",
        }
        row = pe._score_f1(pred, "c")
        self.assertIsNotNone(row)
        self.assertFalse(row["correct"])
        self.assertGreater(row["logloss"], 10.0)

    def test_probability_bucket_and_case_profile(self):
        self.assertEqual(pe._bucket_probability(0.82), "0.80-0.90")
        profile = pe._case_profile(
            {
                "confidence": "MEDIUM",
                "action_state": "SECONDARY",
                "strategy": "router",
                "situation": {"quality": {"evidence_count": 7, "conflict_rate": 0.55, "freshness_score": 0.4}},
            },
            0.71,
        )
        self.assertEqual(profile["conflict_bucket"], "high")
        self.assertEqual(profile["evidence_bucket"], "6+")
        self.assertEqual(profile["freshness_bucket"], "low")

    def test_archive_forward_prediction_db_exports_existing_rows(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as td:
            old_dir = pe.PREDICTIONS_DIR
            old_idx = pe.PREDICTION_INDEX
            try:
                pe.PREDICTIONS_DIR = Path(td) / "predictions"
                pe.PREDICTION_INDEX = Path(td) / "prediction_ids.txt"
                con = sqlite3.connect(":memory:")
                con.execute(
                    """CREATE TABLE forward_prediction(
                        prediction_id TEXT PRIMARY KEY,
                        event_id TEXT,
                        sport TEXT,
                        prediction_cutoff_at_utc TEXT,
                        generated_at_utc TEXT,
                        probability_side_a REAL,
                        probability_side_b REAL,
                        strategy TEXT,
                        model_version TEXT,
                        feature_version TEXT,
                        features_json TEXT,
                        status TEXT
                    )"""
                )
                con.execute(
                    "INSERT INTO forward_prediction VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "db-p1", "e-db", "basketball", "2026-09-25T10:00:00+00:00",
                        "2026-09-25T10:05:00+00:00", 0.35, 0.65, "router",
                        "m1", "f1", '{"matchday_situation":{"status":"PIT_SAFE"}}', "OPEN",
                    ),
                )
                con.commit()
                result = pe.archive_forward_prediction_db(
                    con, "basketball", "2026-09-25T10:06:00+00:00"
                )
                self.assertEqual(result["added"], 1)
                archived = pe._load_jsonl_dir(pe.PREDICTIONS_DIR)
                self.assertEqual(len(archived), 1)
                self.assertEqual(archived[0]["prediction_id"], "db-p1")
                self.assertEqual(archived[0]["strategy"], "router")
                con.close()
            finally:
                pe.PREDICTIONS_DIR = old_dir
                pe.PREDICTION_INDEX = old_idx

    def test_archive_recovers_from_index_interruption_without_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            old_dir = pe.PREDICTIONS_DIR
            old_idx = pe.PREDICTION_INDEX
            try:
                pe.PREDICTIONS_DIR = Path(td) / "predictions"
                pe.PREDICTION_INDEX = Path(td) / "prediction_ids.txt"
                result = [{
                    "sport": "basketball",
                    "predictions": [{
                        "prediction_id": "p-recover",
                        "event_id": "e-recover",
                        "prediction_cutoff_at_utc": "2026-09-25T23:00:00+00:00",
                        "generated_at_utc": "2026-09-25T23:10:00+00:00",
                        "probability_side_a": 0.4,
                        "probability_side_b": 0.6,
                    }],
                }]
                self.assertEqual(pe.archive_predictions(result)["added"], 1)

                # Simulate the crash window: the archive append succeeded but the
                # index write did not happen.
                archive_file = next(pe.PREDICTIONS_DIR.glob("*.jsonl"))
                raw = json.loads(archive_file.read_text(encoding="utf-8").splitlines()[0])
                raw["prediction_id"] = "p-crash-window"
                with archive_file.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(raw, ensure_ascii=False) + "\\n")

                self.assertEqual(pe.archive_predictions([{
                    "sport": "basketball",
                    "predictions": [{
                        **raw,
                        "event_id": "e-crash-window",
                    }],
                }])["added"], 0)
                ids = set(pe.PREDICTION_INDEX.read_text(encoding="utf-8").splitlines())
                self.assertIn("p-crash-window", ids)
                self.assertEqual(len(archive_file.read_text(encoding="utf-8").splitlines()), 2)
            finally:
                pe.PREDICTIONS_DIR = old_dir
                pe.PREDICTION_INDEX = old_idx

    def test_archive_deduplicates_prediction_ids(self):
        with tempfile.TemporaryDirectory() as td:
            old_dir = pe.PREDICTIONS_DIR
            try:
                pe.PREDICTIONS_DIR = Path(td) / "predictions"
                result = [
                    {"sport": "basketball", "predictions": [{
                        "prediction_id": "p1",
                        "event_id": "e1",
                        "event_time_utc": "2026-09-26T00:00:00+00:00",
                        "prediction_cutoff_at_utc": "2026-09-25T23:00:00+00:00",
                        "generated_at_utc": "2026-09-25T23:10:00+00:00",
                        "probability_side_a": 0.4,
                        "probability_side_b": 0.6,
                    }]}
                ]
                self.assertEqual(pe.archive_predictions(result)["added"], 1)
                self.assertEqual(pe.archive_predictions(result)["added"], 0)
                rows = list(pe.PREDICTIONS_DIR.glob("*.jsonl"))
                self.assertEqual(len(rows), 1)
                self.assertEqual(len(rows[0].read_text(encoding="utf-8").splitlines()), 1)
            finally:
                pe.PREDICTIONS_DIR = old_dir


if __name__ == "__main__":
    unittest.main()
