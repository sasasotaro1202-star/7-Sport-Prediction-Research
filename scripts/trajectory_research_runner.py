from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.trajectory_intelligence_oos import (  # noqa: E402
    ENGINE_VERSION,
    build_trajectory_cases,
    evaluate_oos,
    validate_snapshots,
)


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"INVALID_JSONL line={line_no}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"NON_OBJECT_JSONL line={line_no}")
            rows.append(value)
    return rows


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only temporal trajectory evaluator")
    parser.add_argument("--snapshots", default="results/research/trajectory_snapshots.jsonl")
    parser.add_argument("--outcomes", default="results/research/trajectory_outcomes.json")
    parser.add_argument("--output", default="results/research/trajectory_intelligence.json")
    parser.add_argument("--mode", choices=("pre_event", "in_event"), default="pre_event")
    parser.add_argument("--horizons-seconds", default="900,1800,3600,7200")
    parser.add_argument("--n-folds", type=int, default=6)
    parser.add_argument("--min-train-events", type=int, default=24)
    parser.add_argument("--k", type=int, default=20)
    args = parser.parse_args()

    snapshot_path = ROOT / args.snapshots
    outcome_path = ROOT / args.outcomes
    output_path = ROOT / args.output
    horizons = tuple(sorted({int(x) for x in args.horizons_seconds.split(",") if int(x) > 0}))

    if not snapshot_path.exists() or not outcome_path.exists():
        payload = {
            "status": "BLOCKED",
            "engine_version": ENGINE_VERSION,
            "mode": args.mode,
            "reason": "PIT_TRAJECTORY_INPUT_UNAVAILABLE",
            "snapshots_path": str(snapshot_path.relative_to(ROOT)),
            "outcomes_path": str(outcome_path.relative_to(ROOT)),
            "promotion_status": "RESEARCH_ONLY_NO_AUTO_PROMOTION",
        }
        write_json(output_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    try:
        rows = load_jsonl(snapshot_path)
        outcomes = json.loads(outcome_path.read_text(encoding="utf-8"))
    except Exception as exc:
        payload = {
            "status": "FAILED",
            "engine_version": ENGINE_VERSION,
            "reason": f"INPUT_READ_ERROR:{type(exc).__name__}:{exc}",
            "promotion_status": "HOLD_RESEARCH_ONLY_NO_AUTO_PROMOTION",
        }
        write_json(output_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    if not isinstance(outcomes, dict):
        payload = {
            "status": "FAILED",
            "engine_version": ENGINE_VERSION,
            "reason": "OUTCOMES_MUST_BE_OBJECT",
            "promotion_status": "HOLD_RESEARCH_ONLY_NO_AUTO_PROMOTION",
        }
        write_json(output_path, payload)
        return 2

    validation = validate_snapshots(rows, mode=args.mode)
    summary = {
        "status": validation["status"],
        "engine_version": ENGINE_VERSION,
        "mode": args.mode,
        "input_rows": validation["input_rows"],
        "valid_rows": validation["valid_rows"],
        "invalid_rows": validation["invalid_rows"],
        "events": validation["events"],
        "pit_errors": validation["errors"],
        "horizons_seconds": list(horizons),
        "promotion_status": "RESEARCH_ONLY_NO_AUTO_PROMOTION",
    }
    if validation["invalid_rows"]:
        summary["status"] = "FAILED_PIT_GATE"
        summary["reason"] = "PIT validation failed; invalid snapshots were excluded and no score is claimed."
        write_json(output_path, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2

    built = build_trajectory_cases(validation["snapshots"], outcomes, horizons)
    summary["trajectory_cases"] = built["case_count"]
    summary["events_with_cases"] = built["events_with_cases"]
    summary["skipped_cases"] = len(built["skipped"])
    if built["case_count"] == 0:
        summary["status"] = "BLOCKED"
        summary["reason"] = "NO_COMPLETE_PIT_TRAJECTORY_CASES"
        write_json(output_path, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    evaluation = evaluate_oos(
        built["cases"],
        n_folds=args.n_folds,
        min_train_events=args.min_train_events,
        k=args.k,
    )
    summary["evaluation"] = evaluation
    summary["status"] = evaluation.get("status", "UNKNOWN")
    summary["promotion_status"] = "RESEARCH_ONLY_NO_AUTO_PROMOTION"
    write_json(output_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] in {"EVALUATED", "INSUFFICIENT_OOS", "BLOCKED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
