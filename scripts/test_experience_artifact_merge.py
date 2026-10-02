from __future__ import annotations

import json
import tempfile
from pathlib import Path

from src.merge_experience_artifacts import merge_jsonl


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        input_root = root / "input"
        output_root = root / "output"
        (input_root / "a/results/experience").mkdir(parents=True)
        (input_root / "b/results/experience").mkdir(parents=True)
        output_root.mkdir()

        pred_a = {"prediction_id": "p1", "event_id": "e1", "prediction_origin": "AUTOMATED_SCHEDULE"}
        pred_b = {"prediction_id": "p1", "event_id": "e1", "prediction_origin": "AUTOMATED_SCHEDULE", "x": "duplicate"}
        pred_c = {"prediction_id": "p2", "event_id": "e2", "prediction_origin": "ON_DEMAND_REQUEST"}
        (input_root / "a/results/experience/predictions.jsonl").write_text(
            json.dumps(pred_a) + "\n" + json.dumps(pred_c) + "\n",
            encoding="utf-8",
        )
        (input_root / "b/results/experience/predictions.jsonl").write_text(
            json.dumps(pred_b) + "\n",
            encoding="utf-8",
        )

        settle_old = {"prediction_id": "p1", "settled_at_utc": "2026-10-02T01:00:00+00:00"}
        settle_new = {"prediction_id": "p1", "settled_at_utc": "2026-10-02T02:00:00+00:00", "logloss": 0.1}
        (input_root / "a/results/experience/settlements.jsonl").write_text(
            json.dumps(settle_old) + "\n", encoding="utf-8"
        )
        (input_root / "b/results/experience/settlements.jsonl").write_text(
            json.dumps(settle_new) + "\n", encoding="utf-8"
        )

        result = merge_jsonl(input_root, output_root)
        assert result["prediction_rows"] == 3, result
        assert result["prediction_ids"] == 2, result
        assert result["settlement_rows"] == 2, result
        assert result["settlement_ids"] == 1, result

        preds = [
            json.loads(line)
            for line in (output_root / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        settlements = [
            json.loads(line)
            for line in (output_root / "settlements.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        assert [p["prediction_id"] for p in preds] == ["p1", "p2"], preds
        assert settlements[0]["logloss"] == 0.1, settlements

    print("EXPERIENCE_ARTIFACT_MERGE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
