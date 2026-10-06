from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "production_failure_recovery.yml"


def _recovery_script() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Coalesce duplicate recovery requests and retry once\n"
    start = workflow.index(marker)
    run_marker = "        run: |\n"
    start = workflow.index(run_marker, start) + len(run_marker)
    end = workflow.find("\n      - name:", start)
    if end < 0:
        end = len(workflow)
    return textwrap.dedent(workflow[start:end]).rstrip() + "\n"


def _run(main_sha: str, original_sha: str, runs: list[dict[str, object]]) -> list[str]:
    script = _recovery_script()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        script_path = root / "recovery.sh"
        script_path.write_text(script, encoding="utf-8")
        fake_bin = root / "bin"
        fake_bin.mkdir()
        log_path = root / "gh_calls.log"
        fake_gh = fake_bin / "gh"
        fake_gh.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
log_file="$FAKE_GH_LOG"
printf '%s\\n' "$*" >> "$log_file"
if [ "$1" = "api" ]; then
  endpoint="$2"
  if [[ "$endpoint" == */git/ref/heads/main ]]; then
    printf '{"object":{"sha":"%s"}}\\n' "$FAKE_MAIN_SHA"
    exit 0
  fi
  if [[ "$endpoint" == */actions/workflows/*/runs* ]]; then
    printf '%s\\n' "$FAKE_RUNS_JSON"
    exit 0
  fi
  echo "unexpected api endpoint: $endpoint" >&2
  exit 2
fi
case "$1 $2" in
  "workflow run"|"run rerun")
    exit 0
    ;;
  *)
    echo "unexpected gh invocation: $*" >&2
    exit 2
    ;;
esac
""",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)

        env = dict(os.environ)
        env["FAKE_MAIN_SHA"] = main_sha
        env["FAKE_RUNS_JSON"] = json.dumps({"workflow_runs": runs})
        env["FAKE_GH_LOG"] = str(log_path)
        env["RUN_ID"] = "100"
        env["ORIGINAL_SHA"] = original_sha
        env["WORKFLOW_ID"] = "357226230"
        env["REPOSITORY"] = "sasasotaro1202-star/7-Sport-Prediction-Research"
        env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]

        subprocess.run(
            ["bash", str(script_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=env,
        )
        return [
            line.strip()
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def test_active_current_main_run_coalesces_stale_recovery() -> None:
    main = "current-main"
    calls = _run(
        main,
        "failed-old",
        [{"id": 200, "status": "in_progress", "head_sha": main}],
    )
    assert any("actions/workflows/357226230/runs" in call for call in calls)
    assert not any(
        call.startswith("workflow run ") or call.startswith("run rerun ")
        for call in calls
    )


def test_stale_failed_run_dispatches_once_without_active_current_main() -> None:
    calls = _run("current-main", "failed-old", [])
    dispatches = [call for call in calls if call.startswith("workflow run ")]
    assert len(dispatches) == 1
    assert not any(call.startswith("run rerun ") for call in calls)


def test_same_sha_failure_reruns_once_without_active_current_main() -> None:
    calls = _run("same-sha", "same-sha", [])
    reruns = [call for call in calls if call.startswith("run rerun ")]
    assert len(reruns) == 1
    assert not any(call.startswith("workflow run ") for call in calls)


def test_same_sha_failure_coalesces_existing_current_main_retry() -> None:
    main = "same-sha"
    calls = _run(main, main, [{"id": 201, "status": "queued", "head_sha": main}])
    assert not any(
        call.startswith("workflow run ") or call.startswith("run rerun ")
        for call in calls
    )


def main() -> None:
    test_active_current_main_run_coalesces_stale_recovery()
    test_stale_failed_run_dispatches_once_without_active_current_main()
    test_same_sha_failure_reruns_once_without_active_current_main()
    test_same_sha_failure_coalesces_existing_current_main_retry()
    print("PRODUCTION_FAILURE_RECOVERY_DEDUP=PASS")


if __name__ == "__main__":
    main()
