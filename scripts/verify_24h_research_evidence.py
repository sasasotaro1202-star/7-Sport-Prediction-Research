from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "research"


def current_sha() -> str:
    env_sha = os.environ.get("GITHUB_SHA", "").strip()
    if env_sha:
        return env_sha
    p = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return p.stdout.strip()


def load_required(path: Path, sport: str) -> dict:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"missing evidence: {path}")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"invalid JSON: {path}: {type(exc).__name__}:{exc}") from exc
    if not isinstance(obj, dict):
        raise RuntimeError(f"evidence root must be object: {path}")
    if obj.get("sport") != sport:
        raise RuntimeError(f"sport mismatch: {path}: {obj.get('sport')!r} != {sport!r}")
    return obj


def assert_no_production_mutation(obj: dict, path: Path) -> None:
    if obj.get("production_changed") is True:
        raise RuntimeError(f"production_changed=true: {path}")
    if obj.get("production_model_touched") is True:
        raise RuntimeError(f"production_model_touched=true: {path}")


def verify(sport: str) -> dict:
    expected_sha = current_sha()

    primary_path = RESULTS / f"{sport}.json"
    v13_path = RESULTS / f"{sport}_ultimate_v13.json"
    intelligence_path = RESULTS / f"{sport}_ultimate_intelligence.json"

    primary = load_required(primary_path, sport)
    v13 = load_required(v13_path, sport)
    intelligence = load_required(intelligence_path, sport)

    if primary.get("git_commit_sha") != expected_sha:
        raise RuntimeError(
            f"stale primary evidence: {primary_path}: "
            f"{primary.get('git_commit_sha')!r} != {expected_sha!r}"
        )
    if primary.get("status") != "TRAINED":
        raise RuntimeError(
            f"primary research status is not TRAINED: {primary.get('status')!r}"
        )
    if primary.get("holdout_frozen") is not True:
        raise RuntimeError("primary holdout_frozen contract failed")
    if primary.get("production_fit_excludes_holdout") is not True:
        raise RuntimeError("primary production_fit_excludes_holdout contract failed")
    artifact = str(primary.get("artifact_path", ""))
    if not artifact.startswith("models/research/"):
        raise RuntimeError(f"artifact escaped research boundary: {artifact!r}")
    artifact_path = ROOT / artifact
    if not artifact_path.is_file() or artifact_path.stat().st_size <= 0:
        raise RuntimeError(f"missing research model artifact: {artifact_path}")

    if v13.get("status") not in {"EVALUATED", "BLOCKED"}:
        raise RuntimeError(f"unexpected v13 status: {v13.get('status')!r}")
    if intelligence.get("mode") != "RESEARCH_ONLY":
        raise RuntimeError("ultimate intelligence is not research-only")
    if not str(intelligence.get("promotion_status", "")).startswith("HOLD"):
        raise RuntimeError("ultimate intelligence promotion boundary is not HOLD")

    for obj, path in (
        (primary, primary_path),
        (v13, v13_path),
        (intelligence, intelligence_path),
    ):
        assert_no_production_mutation(obj, path)

    return {
        "sport": sport,
        "git_commit_sha": expected_sha,
        "primary_status": primary.get("status"),
        "primary_model_artifact": artifact,
        "v13_status": v13.get("status"),
        "intelligence_mode": intelligence.get("mode"),
        "research_only": True,
        "production_model_touched": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True)
    args = parser.parse_args()
    payload = verify(args.sport)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
