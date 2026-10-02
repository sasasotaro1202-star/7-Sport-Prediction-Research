from __future__ import annotations

import argparse
import json
from pathlib import Path


def merge_jsonl(input_root: Path, output_root: Path) -> dict[str, int]:
    output_root.mkdir(parents=True, exist_ok=True)
    counters = {"prediction_rows": 0, "settlement_rows": 0, "prediction_ids": 0, "settlement_ids": 0}

    existing_predictions: dict[str, dict] = {}
    existing_settlements: dict[str, dict] = {}

    pred_out = output_root / "predictions.jsonl"
    settle_out = output_root / "settlements.jsonl"

    if pred_out.is_file():
        for line in pred_out.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            pid = str(row.get("prediction_id") or "")
            if pid:
                existing_predictions[pid] = row

    if settle_out.is_file():
        for line in settle_out.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            pid = str(row.get("prediction_id") or "")
            if pid:
                existing_settlements[pid] = row

    for path in sorted(input_root.glob("**/results/experience/predictions.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            pid = str(row.get("prediction_id") or "")
            if not pid:
                continue
            counters["prediction_rows"] += 1
            existing_predictions.setdefault(pid, row)

    for path in sorted(input_root.glob("**/results/experience/settlements.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            pid = str(row.get("prediction_id") or "")
            if not pid:
                continue
            counters["settlement_rows"] += 1
            previous = existing_settlements.get(pid)
            if previous is None:
                existing_settlements[pid] = row
            else:
                # Settlement is immutable for a prediction id; retain the latest
                # explicit record only when a repair/replay writes it again.
                if str(row.get("settled_at_utc") or "") >= str(previous.get("settled_at_utc") or ""):
                    existing_settlements[pid] = row

    counters["prediction_ids"] = len(existing_predictions)
    counters["settlement_ids"] = len(existing_settlements)

    pred_out.write_text(
        "".join(json.dumps(existing_predictions[k], ensure_ascii=False, sort_keys=True) + "\n"
                for k in sorted(existing_predictions)),
        encoding="utf-8",
    )
    settle_out.write_text(
        "".join(json.dumps(existing_settlements[k], ensure_ascii=False, sort_keys=True) + "\n"
                for k in sorted(existing_settlements)),
        encoding="utf-8",
    )
    return counters


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    result = merge_jsonl(args.input_root, args.output_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
