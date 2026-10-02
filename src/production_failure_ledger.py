#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "results/failure_ledger.jsonl"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify(failed_jobs: list[str], conclusion: str) -> str:
    names = " ".join(failed_jobs).lower()
    if "pit" in names:
        return "PIT_WORKFLOW_FAILURE"
    if "collect" in names:
        return "COLLECTION_WORKFLOW_FAILURE"
    if "merge, research" in names or "research" in names or "release gate" in names:
        return "RESEARCH_RELEASE_WORKFLOW_FAILURE"
    if conclusion in {"timed_out", "startup_failure"}:
        return "WORKFLOW_RUNTIME_FAILURE"
    return "WORKFLOW_JOB_FAILURE"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--run-attempt", required=True, type=int)
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--conclusion", required=True)
    ap.add_argument("--event", required=True)
    ap.add_argument("--failed-job", action="append", default=[])
    args = ap.parse_args()

    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    existing_ids: set[str] = set()
    if LEDGER.is_file():
        for line in LEDGER.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                obj = json.loads(line)
            except Exception:
                continue
            existing_ids.add(f"{obj.get('run_id')}:{obj.get('run_attempt')}")

    key = f"{args.run_id}:{args.run_attempt}"
    if key in existing_ids:
        print(f"FAILURE_LEDGER_DUPLICATE=SKIP key={key}")
        return 0

    failed_jobs = sorted(dict.fromkeys(str(x) for x in args.failed_job if str(x).strip()))
    entry = {
        "recorded_at_utc": utcnow(),
        "run_id": str(args.run_id),
        "run_attempt": int(args.run_attempt),
        "workflow": str(args.workflow),
        "head_sha": str(args.head_sha),
        "conclusion": str(args.conclusion),
        "event": str(args.event),
        "failure_class": classify(failed_jobs, str(args.conclusion)),
        "failed_jobs": failed_jobs,
        "status": "RECORDED",
        "source": "github_actions_workflow_run",
        "policy": "append_only;idempotent_by_run_id_and_attempt;unknown_details_are_not_inferred",
    }
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"FAILURE_LEDGER_RECORDED={key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
