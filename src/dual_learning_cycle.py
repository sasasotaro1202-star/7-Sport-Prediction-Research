from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "results" / "research" / "dual_learning_cycle.json"
LOG_DIR = ROOT / "results" / "research" / "dual_learning_logs"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _command(name: str, sport: str | None) -> list[str]:
    if name == "experience":
        return [sys.executable, "-m", "src.experience_learning"]
    if name == "research":
        cmd = [sys.executable, "-m", "src.research_cycle_strict"]
        if sport:
            cmd += ["--sport", sport]
        return cmd
    raise ValueError(f"unknown lane: {name}")


def _write_evidence(payload: dict) -> None:
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def run(sport: str | None = None, research_command: Sequence[str] | None = None) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    started = utc_now()
    wall_start = time.monotonic()

    experience_cmd = _command("experience", sport)
    historical_cmd = (
        _command("research", sport)
        if research_command is None
        else [str(x) for x in research_command]
    )

    exp_log = (LOG_DIR / "experience_learning.log").open("w", encoding="utf-8")
    historical_log = (LOG_DIR / "historical_research.log").open("w", encoding="utf-8")

    exp = None
    historical = None
    payload = {
        "version": "dual-learning-cycle-v1",
        "status": "RUNNING",
        "started_at_utc": started,
        "sport": sport,
        "parallel": True,
        "lanes": {
            "experience": {
                "purpose": "learn_from_matured_prediction_experience_only",
                "command": experience_cmd,
                "log": "dual_learning_logs/experience_learning.log",
            },
            "historical": {
                "purpose": "learn_from_historical_games_with_chronological_oos",
                "command": historical_cmd,
                "log": "dual_learning_logs/historical_research.log",
            },
        },
        "safety": {
            "experience_outcomes_reused_in_historical_oos": False,
            "historical_oos_used_for_experience_memory": False,
            "production_model_changed_by_this_orchestrator": False,
            "automatic_promotion": False,
            "failure_handling": "fail_closed_no_success_masking",
        },
    }
    _write_evidence(payload)

    try:
        exp = subprocess.Popen(
            experience_cmd,
            cwd=ROOT,
            stdout=exp_log,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
        )
        payload["lanes"]["experience"]["pid"] = exp.pid
        payload["lanes"]["experience"]["started_at_utc"] = utc_now()

        historical = subprocess.Popen(
            historical_cmd,
            cwd=ROOT,
            stdout=historical_log,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
        )
        payload["lanes"]["historical"]["pid"] = historical.pid
        payload["lanes"]["historical"]["started_at_utc"] = utc_now()
        _write_evidence(payload)

        while exp.poll() is None and historical.poll() is None:
            time.sleep(0.5)

        exp_rc_now = exp.poll()
        historical_rc_now = historical.poll()

        if exp_rc_now not in (None, 0) and historical_rc_now is None:
            historical.terminate()
            try:
                historical.wait(timeout=20)
            except subprocess.TimeoutExpired:
                historical.kill()
                historical.wait()
        if historical_rc_now not in (None, 0) and exp_rc_now is None:
            exp.terminate()
            try:
                exp.wait(timeout=20)
            except subprocess.TimeoutExpired:
                exp.kill()
                exp.wait()

        exp_rc = exp.wait()
        historical_rc = historical.wait()
        finished = utc_now()
        success = exp_rc == 0 and historical_rc == 0

        payload.update({
            "finished_at_utc": finished,
            "duration_seconds": round(time.monotonic() - wall_start, 3),
            "status": "SUCCESS" if success else "FAILED",
        })
        payload["lanes"]["experience"]["returncode"] = exp_rc
        payload["lanes"]["experience"]["finished_at_utc"] = finished
        payload["lanes"]["historical"]["returncode"] = historical_rc
        payload["lanes"]["historical"]["finished_at_utc"] = finished
        if not success:
            payload["failure"] = {
                "experience_returncode": exp_rc,
                "historical_returncode": historical_rc,
            }
        _write_evidence(payload)
        return 0 if success else 1
    except Exception as exc:
        payload.update({
            "finished_at_utc": utc_now(),
            "duration_seconds": round(time.monotonic() - wall_start, 3),
            "status": "FAILED",
            "failure": {
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            },
        })
        if exp is not None:
            payload["lanes"]["experience"]["returncode"] = exp.poll()
        if historical is not None:
            payload["lanes"]["historical"]["returncode"] = historical.poll()
        _write_evidence(payload)
        raise
    finally:
        if exp is not None and exp.poll() is None:
            exp.kill()
            exp.wait()
        if historical is not None and historical.poll() is None:
            historical.kill()
            historical.wait()
        exp_log.close()
        historical_log.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default=None)
    return run(sport=parser.parse_args().sport)


if __name__ == "__main__":
    raise SystemExit(main())
