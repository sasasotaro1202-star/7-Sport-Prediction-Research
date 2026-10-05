from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


EXPECTED_STAGES = {
    1: "basketball",
    2: "volleyball",
    3: "ufc",
    4: "rizin",
    5: "valorant",
}
ALLOWED_STATUS = {"PASS", "DEGRADED", "FAILED"}


def current_remote_sha() -> str:
    env = os.environ.get("GITHUB_SHA", "").strip()
    if not env:
        raise RuntimeError("GITHUB_SHA is required for 24H reconciliation")
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("GH_TOKEN", "").strip()
    if not repo or not token:
        return env
    proc = subprocess.run(
        ["gh", "api", f"repos/{repo}/git/ref/heads/main", "--jq", ".object.sha"],
        text=True,
        capture_output=True,
        check=True,
    )
    remote = proc.stdout.strip()
    if not remote:
        raise RuntimeError("remote main SHA is empty")
    return remote


def load_stage_files(root: Path) -> list[Path]:
    return sorted(root.rglob("stage_*_final.json"))


def reconcile(root: Path) -> dict:
    expected_sha = os.environ.get("GITHUB_SHA", "").strip()
    remote_sha = current_remote_sha()
    if remote_sha != expected_sha:
        raise RuntimeError(
            f"STALE_24H_RUN remote_main={remote_sha} workflow_sha={expected_sha}"
        )

    files = load_stage_files(root)
    by_stage: dict[int, tuple[Path, dict]] = {}
    invalid: list[dict] = []

    for path in files:
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            invalid.append({"path": str(path), "reason": f"invalid_json:{type(exc).__name__}"})
            continue
        if not isinstance(obj, dict):
            invalid.append({"path": str(path), "reason": "root_not_object"})
            continue
        try:
            stage = int(obj["stage"])
        except (KeyError, TypeError, ValueError):
            invalid.append({"path": str(path), "reason": "missing_stage"})
            continue
        if stage not in EXPECTED_STAGES:
            invalid.append({"path": str(path), "reason": f"unexpected_stage:{stage}"})
            continue
        if stage in by_stage:
            invalid.append({"path": str(path), "reason": f"duplicate_stage:{stage}"})
            continue
        by_stage[stage] = (path, obj)

    stages: list[dict] = []
    missing: list[int] = []
    for stage, expected_sport in EXPECTED_STAGES.items():
        pair = by_stage.get(stage)
        if pair is None:
            missing.append(stage)
            continue
        path, obj = pair
        sport = obj.get("sport")
        status = str(obj.get("status") or "")
        sha = str(obj.get("github_sha") or "")
        stage_row = {
            "stage": stage,
            "sport": sport,
            "status": status,
            "github_sha": sha,
            "path": str(path),
            "iterations": obj.get("iterations"),
            "command_count": obj.get("command_count"),
            "critical_failures": obj.get("critical_failures") or [],
            "degraded_tasks": obj.get("degraded_tasks") or [],
        }
        stages.append(stage_row)
        if sport != expected_sport:
            invalid.append({
                "path": str(path),
                "reason": f"sport_mismatch:{sport!r}!={expected_sport!r}",
            })
        if status not in ALLOWED_STATUS:
            invalid.append({"path": str(path), "reason": f"invalid_status:{status!r}"})
        if sha and sha != expected_sha:
            invalid.append({
                "path": str(path),
                "reason": f"stage_sha_mismatch:{sha!r}!={expected_sha!r}",
            })

    failed = [row["stage"] for row in stages if row["status"] == "FAILED"]
    degraded = [row["stage"] for row in stages if row["status"] == "DEGRADED"]

    if missing or invalid or failed:
        overall = "FAILED"
    elif degraded:
        overall = "DEGRADED"
    else:
        overall = "PASS"

    return {
        "version": "24h-final-reconciliation-v1",
        "workflow_sha": expected_sha,
        "remote_main_sha": remote_sha,
        "expected_stage_count": len(EXPECTED_STAGES),
        "observed_stage_count": len(stages),
        "missing_stages": missing,
        "invalid_evidence": invalid,
        "failed_stages": failed,
        "degraded_stages": degraded,
        "status": overall,
        "research_only": True,
        "automatic_promotion": False,
        "stages": stages,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="results/24h_stage_artifacts")
    args = parser.parse_args()
    root = Path(args.root)
    payload = reconcile(root)
    out_dir = Path("results/24h_marathon")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "final_reconciliation.json"
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if payload["status"] == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
