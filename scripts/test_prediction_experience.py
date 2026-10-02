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

    def test_score_archive_rejects_invalid_verified_outcome_label(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as td:
            old_pred = pe.PREDICTIONS_DIR
            old_sett = pe.SETTLEMENTS_DIR
            old_sum = pe.SUMMARY_OUT
            try:
                pe.PREDICTIONS_DIR = Path(td) / "predictions"
                pe.SETTLEMENTS_DIR = Path(td) / "settlements"
                pe.SUMMARY_OUT = Path(td) / "summary.json"
                pe.PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
                (pe.PREDICTIONS_DIR / "2026-09-26.jsonl").write_text(
                    json.dumps({
                        "prediction_id": "bad-outcome", "sport": "basketball", "event_id": "e1",
                        "event_time_utc": "2026-09-26T10:00:00+00:00",
                        "prediction_cutoff_at_utc": "2026-09-26T09:00:00+00:00",
                        "generated_at_utc": "2026-09-26T09:01:00+00:00",
                        "probability_side_a": 0.6, "probability_side_b": 0.4,
                    }) + "\n",
                    encoding="utf-8",
                )
                old_connect = pe._connect_dbs
                db = sqlite3.connect(":memory:")
                db.execute("CREATE TABLE event_outcome(outcome TEXT, outcome_status TEXT, source TEXT, event_id TEXT)")
                db.execute("INSERT INTO event_outcome VALUES ('HOME','VERIFIED','test','e1')")
                pe._connect_dbs = lambda: {"basketball": db}
                with self.assertRaisesRegex(RuntimeError, "INVALID_ACTUAL_OUTCOME_LABEL:HOME"):
                    pe.score_archive()
                pe._connect_dbs = old_connect
                db.close()
            finally:
                pe.PREDICTIONS_DIR = old_pred
                pe.SETTLEMENTS_DIR = old_sett
                pe.SUMMARY_OUT = old_sum

    def test_f1_score_rejects_out_of_range_probability(self):
        pred = {
            "drivers": [
                {"participant_id": "a", "probability": 1.2},
                {"participant_id": "b", "probability": -0.2},
            ]
        }
        with self.assertRaisesRegex(RuntimeError, "INVALID_F1_PROBABILITIES:out_of_range"):
            pe._score_f1(pred, "a")

    def test_f1_score_rejects_non_unit_probability_sum(self):
        pred = {
            "drivers": [
                {"participant_id": "a", "probability": 0.6},
                {"participant_id": "b", "probability": 0.2},
            ]
        }
        with self.assertRaisesRegex(RuntimeError, "INVALID_F1_PROBABILITIES:sum_not_one"):
            pe._score_f1(pred, "a")

    def test_f1_score_rejects_duplicate_participant_id(self):
        pred = {
            "drivers": [
                {"participant_id": "a", "probability": 0.6},
                {"participant_id": "a", "probability": 0.4},
            ]
        }
        with self.assertRaisesRegex(RuntimeError, "INVALID_F1_PROBABILITIES:duplicate_participant_id"):
            pe._score_f1(pred, "a")

    def test_f1_score_accepts_valid_probability_vector(self):
        row = pe._score_f1(
            {
                "drivers": [
                    {"participant_id": "a", "probability": 0.6},
                    {"participant_id": "b", "probability": 0.4},
                ]
            },
            "a",
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["predicted_outcome_participant_id"], "a")
        self.assertTrue(row["correct"])

    def test_score_binary_rejects_out_of_range_probability(self):
        pred = {"probability_side_a": 1.2, "probability_side_b": -0.2}
        with self.assertRaisesRegex(RuntimeError, "INVALID_BINARY_PROBABILITIES:out_of_range"):
            pe._score_binary(pred, "A")

    def test_score_binary_rejects_non_unit_probability_sum(self):
        pred = {"probability_side_a": 0.7, "probability_side_b": 0.2}
        with self.assertRaisesRegex(RuntimeError, "INVALID_BINARY_PROBABILITIES:sum_not_one"):
            pe._score_binary(pred, "A")

    def test_score_binary_accepts_valid_probability_pair(self):
        row = pe._score_binary(
            {"probability_side_a": 0.7, "probability_side_b": 0.3}, "A"
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["predicted_outcome"], "A")
        self.assertTrue(row["correct"])

    def test_summary_groups_competition_and_prediction_timing(self):
        rows = [
            {
                "settlement_status": "SCORED",
                "correct": True,
                "logloss": 0.2,
                "brier": 0.1,
                "sport": "basketball",
                "strategy": "router",
                "confidence": "MEDIUM",
                "action_state": "SECONDARY",
                "probability_bucket": "0.70-0.80",
                "experience_class": "CORRECT_NONHIGH_CONF",
                "competition_profile": {"profile_id": "basketball:bleague"},
                "prediction_timing_status": "EARLY",
            },
            {
                "settlement_status": "SCORED",
                "correct": False,
                "logloss": 1.2,
                "brier": 0.8,
                "sport": "basketball",
                "strategy": "router",
                "confidence": "HIGH",
                "action_state": "PRIMARY",
                "probability_bucket": "0.80-0.90",
                "experience_class": "WRONG_OVERCONFIDENT",
                "competition_profile": {"profile_id": "basketball:asian_games"},
                "prediction_timing_status": "LATE",
            },
        ]
        summary = pe._summary(rows, 2, {})
        self.assertIn("basketball:bleague", summary["by_competition_profile"])
        self.assertIn("basketball:asian_games", summary["by_competition_profile"])
        self.assertIn("EARLY", summary["by_prediction_timing_status"])
        self.assertIn("LATE", summary["by_prediction_timing_status"])


    def test_summary_canonicalizes_multiple_snapshots_per_event(self):
        rows = [
            {
                "settlement_status": "SCORED",
                "correct": True,
                "logloss": 0.15,
                "brier": 0.05,
                "sport": "basketball",
                "event_id": "event-1",
                "market": "winner_binary",
                "prediction_id": "p60",
                "event_time_utc": "2026-09-30T10:00:00+00:00",
                "prediction_cutoff_at_utc": "2026-09-30T09:00:00+00:00",
                "generated_at_utc": "2026-09-30T09:01:00+00:00",
                "target_lead_minutes": 60,
                "competition_profile": {"profile_id": "basketball:bleague"},
            },
            {
                "settlement_status": "SCORED",
                "correct": False,
                "logloss": 1.50,
                "brier": 0.90,
                "sport": "basketball",
                "event_id": "event-1",
                "market": "winner_binary",
                "prediction_id": "p30",
                "event_time_utc": "2026-09-30T10:00:00+00:00",
                "prediction_cutoff_at_utc": "2026-09-30T09:30:00+00:00",
                "generated_at_utc": "2026-09-30T09:31:00+00:00",
                "target_lead_minutes": 30,
                "competition_profile": {"profile_id": "basketball:bleague"},
            },
        ]
        summary = pe._summary(rows, 2, {})
        self.assertEqual(summary["resolved_scored_total"], 2)
        self.assertEqual(summary["canonical_event_sample_total"], 1)
        self.assertEqual(summary["overall"]["n"], 1)
        self.assertEqual(summary["snapshot_overall"]["n"], 2)
        self.assertFalse(summary["overall"]["accuracy"] == summary["snapshot_overall"]["accuracy"])
        self.assertEqual(summary["canonical_by_target_lead_minutes"]["30"]["n"], 1)
        self.assertEqual(summary["snapshot_correct_total"], 1)
        self.assertEqual(summary["correct_total"], 0)

    def test_canonical_excludes_invalid_timing_without_replacing_with_zero(self):
        rows = [
            {
                "settlement_status": "SCORED",
                "correct": True,
                "logloss": 0.2,
                "brier": 0.1,
                "sport": "ufc",
                "event_id": "event-valid",
                "market": "winner_binary",
                "prediction_id": "valid",
                "event_time_utc": "2026-09-30T10:00:00+00:00",
                "prediction_cutoff_at_utc": "2026-09-30T09:00:00+00:00",
                "generated_at_utc": "2026-09-30T09:01:00+00:00",
            },
            {
                "settlement_status": "SCORED",
                "correct": False,
                "logloss": 2.0,
                "brier": 1.0,
                "sport": "ufc",
                "event_id": "event-invalid",
                "market": "winner_binary",
                "prediction_id": "invalid",
                "event_time_utc": "2026-09-30T10:00:00+00:00",
                "prediction_cutoff_at_utc": "2026-09-30T11:00:00+00:00",
                "generated_at_utc": "2026-09-30T11:01:00+00:00",
            },
        ]
        summary = pe._summary(rows, 2, {})
        self.assertEqual(summary["canonical_event_sample_total"], 1)
        self.assertEqual(summary["canonical_excluded_invalid_timing"], 1)
        self.assertEqual(summary["overall"]["n"], 1)

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
                    fh.write(json.dumps(raw, ensure_ascii=False) + "\n")

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

    def test_settlement_loader_rejects_conflicting_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as td:
            old_dir = pe.SETTLEMENTS_DIR
            try:
                pe.SETTLEMENTS_DIR = Path(td) / "settlements"
                pe.SETTLEMENTS_DIR.mkdir(parents=True)
                row = {
                    "prediction_id": "s-conflict",
                    "settlement_status": "SCORED",
                    "correct": True,
                    "actual_outcome": "A",
                }
                other = dict(row, correct=False)
                path = pe.SETTLEMENTS_DIR / "2026-10-01.jsonl"
                path.write_text(
                    json.dumps(row) + "\n" + json.dumps(other) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(RuntimeError, "CONFLICTING_SETTLEMENT_DUPLICATE"):
                    pe._load_settlements()
            finally:
                pe.SETTLEMENTS_DIR = old_dir

    def test_settlement_loader_rejects_missing_prediction_id(self):
        with tempfile.TemporaryDirectory() as td:
            old_dir = pe.SETTLEMENTS_DIR
            try:
                pe.SETTLEMENTS_DIR = Path(td) / "settlements"
                pe.SETTLEMENTS_DIR.mkdir(parents=True)
                (pe.SETTLEMENTS_DIR / "2026-10-01.jsonl").write_text(
                    json.dumps({"settlement_status": "SCORED"}) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(RuntimeError, "INVALID_SETTLEMENT_MISSING_PREDICTION_ID"):
                    pe._load_settlements()
            finally:
                pe.SETTLEMENTS_DIR = old_dir


if __name__ == "__main__":
    unittest.main()
