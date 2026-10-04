from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPORTS = ("valorant", "basketball", "volleyball", "ufc", "rizin")
HORIZONS_BY_SPORT = {
    "valorant": "60,180,300,600",
    "basketball": "120,300,600,1200",
    "volleyball": "60,180,300,600",
    "ufc": "60,120,300,600",
    "rizin": "60,120,300,600",
}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"INVALID_JSONL_OBJECT:{path}:line={line_no}")
            rows.append(obj)
    return rows


def write_jsonl_dedup(path: Path, rows: list[dict], key: str = "snapshot_id") -> int:
    merged = {}
    for row in rows:
        value = str(row.get(key) or "")
        if not value:
            continue
        merged[value] = row
    ordered = sorted(
        merged.values(),
        key=lambda r: (
            str(r.get("event_time_utc") or ""),
            str(r.get("event_id") or ""),
            str(r.get("prediction_time_utc") or ""),
            str(r.get(key) or ""),
        ),
    )
    content = "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in ordered)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return int(old != content)


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"INVALID_JSON:{path}")
    return obj


def merge_outcomes(path: Path, additions: dict[str, dict]) -> int:
    current = read_json(path)
    merged = dict(current)
    for event_id, outcome in additions.items():
        if event_id not in merged:
            merged[event_id] = outcome
        else:
            # Deterministic conflict policy: retain the existing verified record
            # unless the new record is also verified and has a later explicit
            # observed_at_utc.
            old = merged[event_id]
            old_verified = str(old.get("outcome_status") or "").upper() == "VERIFIED"
            new_verified = str(outcome.get("outcome_status") or "").upper() == "VERIFIED"
            if (not old_verified and new_verified) or (
                old_verified and new_verified and
                str(outcome.get("observed_at_utc") or "") > str(old.get("observed_at_utc") or "")
            ):
                merged[event_id] = outcome
    content = json.dumps(dict(sorted(merged.items())), ensure_ascii=False, indent=2) + "\n"
    old_content = path.read_text(encoding="utf-8") if path.exists() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return int(old_content != content)


def run_eval(sport: str) -> dict:
    from tempfile import NamedTemporaryFile

    snapshot_path = ROOT / "results/research" / f"trajectory_snapshots_{sport}.jsonl"
    outcome_path = ROOT / "results/research" / f"trajectory_outcomes_{sport}.json"
    output_path = ROOT / "results/research" / f"trajectory_intelligence_{sport}.json"

    cmd = [
        "python", "scripts/trajectory_research_runner.py",
        "--snapshots", str(snapshot_path.relative_to(ROOT)),
        "--outcomes", str(outcome_path.relative_to(ROOT)),
        "--output", str(output_path.relative_to(ROOT)),
        "--mode", "in_event",
        "--horizons-seconds", HORIZONS_BY_SPORT.get(sport, "60,180,300,600"),
        "--n-folds", "6",
        "--min-train-events", "24",
        "--k", "20",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout)
    if proc.returncode not in (0,):
        raise RuntimeError(f"TRAJECTORY_EVALUATION_FAILED:{sport}:exit={proc.returncode}")
    return read_json(output_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", default="trajectory_artifacts")
    parser.add_argument("--sports", default=",".join(SPORTS))
    parser.add_argument("--skip-eval", action="store_true")
    args = parser.parse_args()

    artifact_root = ROOT / args.artifact_root
    sports = tuple(x.strip() for x in args.sports.split(",") if x.strip())

    changed = {}
    reports = {}
    for sport in sports:
        artifact_dir = artifact_root / f"trajectory-delta-{sport}"
        live_delta = artifact_dir / f"trajectory_snapshots_{sport}.jsonl"
        live_outcome = artifact_dir / f"trajectory_outcomes_{sport}.json"
        live_report = artifact_dir / f"trajectory_collect_{sport}.json"

        ledger = ROOT / "results/research" / f"trajectory_snapshots_{sport}.jsonl"
        outcomes = ROOT / "results/research" / f"trajectory_outcomes_{sport}.json"

        delta_rows = read_jsonl(live_delta)
        old_rows = read_jsonl(ledger)
        changed[sport] = {
            "snapshots_changed": bool(write_jsonl_dedup(ledger, old_rows + delta_rows)),
            "delta_snapshots": len(delta_rows),
        }

        additions = read_json(live_outcome) if live_outcome.exists() else {}
        if not isinstance(additions, dict):
            raise ValueError(f"INVALID_OUTCOME_DELTA:{sport}")
        changed[sport]["outcomes_changed"] = bool(merge_outcomes(outcomes, additions))
        changed[sport]["delta_outcomes"] = len(additions)
        reports[sport] = read_json(live_report) if live_report.exists() else {"status": "UNKNOWN"}

    evaluation = {}
    if not args.skip_eval:
        for sport in sports:
            evaluation[sport] = run_eval(sport)

    state = {
        "version": 1,
        "engine_version": "trajectory-intelligence-v1",
        "status": "UNKNOWN",
        "promotion_status": "RESEARCH_ONLY_NO_AUTO_PROMOTION",
        "sports": {},
    }
    for sport in sports:
        snap_path = ROOT / "results/research" / f"trajectory_snapshots_{sport}.jsonl"
        outcome_path = ROOT / "results/research" / f"trajectory_outcomes_{sport}.json"
        snap_count = len(read_jsonl(snap_path))
        outcome_count = len(read_json(outcome_path))
        eval_obj = evaluation.get(sport) or {}
        state["sports"][sport] = {
            "snapshot_count": snap_count,
            "outcome_count": outcome_count,
            "collector_status": reports.get(sport, {}).get("status", "UNKNOWN"),
            "evaluation_status": eval_obj.get("status", "UNKNOWN"),
            "oos_event_rows": eval_obj.get("oos_event_rows"),
            "state_mae_by_horizon": eval_obj.get("state_mae_by_horizon"),
            "logloss_improvement_vs_prior": eval_obj.get("logloss_improvement_vs_prior"),
            "fold_logloss_improvement_vs_prior": eval_obj.get("fold_logloss_improvement_vs_prior"),
            "promotion_status": "RESEARCH_ONLY_NO_AUTO_PROMOTION",
        }

    statuses = [str(v.get("evaluation_status") or "UNKNOWN") for v in state["sports"].values()]
    if any(x == "EVALUATED" for x in statuses):
        state["status"] = "READY"
    elif any(x == "INSUFFICIENT_OOS" for x in statuses):
        state["status"] = "INSUFFICIENT_OOS"
    else:
        state["status"] = "BLOCKED"

    state_path = ROOT / "results/research/trajectory_system_state.json"
    state_content = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    old_state = state_path.read_text(encoding="utf-8") if state_path.exists() else ""
    state_path.write_text(state_content, encoding="utf-8")
    changed["_state_changed"] = old_state != state_content

    print(json.dumps({
        "changed": changed,
        "state": state,
        "commit_candidate": any(
            bool(x) if isinstance(x, bool) else any(bool(v) for v in x.values())
            for k, x in changed.items()
            if k != "_state_changed"
        ) or changed["_state_changed"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
