from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/x_social_v1.sqlite"


def parse_dt(value: str) -> datetime:
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def x_activity_delta(connection: sqlite3.Connection, event_id: str, cutoff: str) -> np.ndarray:
    rows = connection.execute(
        """
        SELECT side,
               COUNT(*) AS posts,
               COUNT(DISTINCT author_id) AS authors,
               COALESCE(SUM(like_count),0) AS likes,
               COALESCE(SUM(reply_count),0) AS replies,
               COALESCE(SUM(repost_count),0) AS reposts,
               COALESCE(SUM(quote_count),0) AS quotes
          FROM x_post
         WHERE event_id=?
           AND pit_status='ELIGIBLE'
           AND source_available_at_utc IS NOT NULL
           AND source_available_at_utc<=?
           AND created_at_utc<=?
         GROUP BY side
        """,
        (event_id, cutoff, cutoff),
    ).fetchall()
    by_side = {row[0]: row[1:] for row in rows}

    def side(name: str) -> np.ndarray:
        return np.asarray(by_side.get(name, (0, 0, 0, 0, 0, 0)), dtype=float)

    # This is an experimental feature vector only. It is deliberately not
    # imported by the production prediction path.
    return np.log1p(side("A")) - np.log1p(side("B"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline-only evaluation of X-derived PIT-safe features")
    parser.add_argument("--labels", required=True, help="CSV: event_id,cutoff_at_utc,outcome (A/B)")
    parser.add_argument("--test-frac", type=float, default=0.20)
    args = parser.parse_args()

    labels = []
    with open(args.labels, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("event_id") and row.get("cutoff_at_utc") and row.get("outcome") in {"A", "B"}:
                labels.append(row)
    labels.sort(key=lambda row: (parse_dt(row["cutoff_at_utc"]), row["event_id"]))

    if not DB.exists():
        print(json.dumps({
            "status": "DEFERRED",
            "reason": "X social database does not exist yet",
            "production_model_touched": False,
        }, ensure_ascii=False, indent=2))
        return 0

    connection = sqlite3.connect(DB)
    X, y, deferred = [], [], []
    for row in labels:
        features = x_activity_delta(connection, row["event_id"], row["cutoff_at_utc"])
        if not np.isfinite(features).all() or np.allclose(features, 0):
            deferred.append(row["event_id"])
            continue
        X.append(features)
        y.append(1 if row["outcome"] == "A" else 0)
    connection.close()

    if len(X) < 20 or len(set(y)) < 2:
        print(json.dumps({
            "status": "DEFERRED",
            "reason": "insufficient_X_PIT_rows",
            "usable_rows": len(X),
            "deferred_rows": len(deferred),
            "production_model_touched": False,
        }, ensure_ascii=False, indent=2))
        return 0

    X = np.asarray(X)
    y = np.asarray(y)
    split = max(10, int(len(y) * (1.0 - args.test_frac)))
    if (
        len(y) - split < 5
        or len(set(y[:split])) < 2
        or len(set(y[split:])) < 2
    ):
        print(json.dumps({
            "status": "DEFERRED",
            "reason": "insufficient_chronological_train_or_test_class_support",
            "usable_rows": len(y),
            "train_rows": split,
            "test_rows": len(y) - split,
            "production_model_touched": False,
        }, ensure_ascii=False, indent=2))
        return 0

    model = LogisticRegression(max_iter=1000)
    model.fit(X[:split], y[:split])
    probability = model.predict_proba(X[split:])[:, 1]
    truth = y[split:]

    report = {
        "status": "EVALUATED",
        "feature_version": "x-social-activity-v1",
        "chronological_holdout": True,
        "train_rows": split,
        "test_rows": len(truth),
        "metrics": {
            "logloss": log_loss(truth, probability, labels=[0, 1]),
            "brier": brier_score_loss(truth, probability),
            "accuracy": accuracy_score(truth, probability >= 0.5),
            "auc": roc_auc_score(truth, probability),
        },
        "deferred_rows": len(deferred),
        "production_model_touched": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
