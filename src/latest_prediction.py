"""Canonical fresh-prediction request entrypoint.

Never serves an older prediction as a substitute for a failed refresh.
Every request refreshes the current data for the requested active-scope sports,
then runs the canonical future predictor and verifies that both collection and
prediction timestamps are newer than the request start.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOPE_PATH = ROOT / "config/PROJECT_SCOPE_POLICY.json"
FRESHNESS_PATH = ROOT / "config/PREDICTION_FRESHNESS_POLICY.json"
COLLECTION_REPORT = ROOT / "results/v45/production_run.json"
PREDICTION_REPORT = ROOT / "results/future_predictions.json"
ARCHIVE_ROOT = ROOT / "results/latest_predictions"
LATEST_PREDICTION_TIMEOUT_ENV = "V45_LATEST_PREDICTION_COMMAND_TIMEOUT_SECONDS"
LATEST_PREDICTION_TIMEOUT_DEFAULT_SECONDS = 600.0
TERMINATION_GRACE_SECONDS = 15.0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def read_json(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"MISSING_OR_EMPTY:{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"INVALID_JSON:{path}:{type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"INVALID_JSON_ROOT:{path}")
    return value


def active_scope() -> list[str]:
    scope = read_json(SCOPE_PATH).get("active_prediction_scope")
    if not isinstance(scope, list) or not scope or any(not isinstance(x, str) for x in scope):
        raise RuntimeError("INVALID_ACTIVE_PREDICTION_SCOPE")
    return list(dict.fromkeys(scope))


def _command_timeout_seconds() -> float:
    raw = os.getenv(
        LATEST_PREDICTION_TIMEOUT_ENV,
        str(LATEST_PREDICTION_TIMEOUT_DEFAULT_SECONDS),
    )
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"INVALID_{LATEST_PREDICTION_TIMEOUT_ENV}:{raw!r}"
        ) from exc
    if value <= 0:
        raise RuntimeError(f"INVALID_{LATEST_PREDICTION_TIMEOUT_ENV}:{raw!r}")
    return value


def _signal_process_group(proc: subprocess.Popen[str], sig: int) -> None:
    if os.name == "posix":
        try:
            os.killpg(os.getpgid(proc.pid), sig)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.send_signal(sig)
    except (ProcessLookupError, OSError):
        pass


def _terminate_process_tree(proc: subprocess.Popen[str]) -> tuple[str, str]:
    """Terminate the child process and descendants, returning captured output."""
    _signal_process_group(proc, signal.SIGTERM)
    try:
        return proc.communicate(timeout=TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _signal_process_group(proc, signal.SIGKILL)
        return proc.communicate()


def _run(
    args: list[str],
    *,
    force_refresh: bool = False,
    timeout_seconds: float | None = None,
) -> None:
    env = None
    if force_refresh:
        env = dict(os.environ)
        env["V45_FORCE_REFRESH"] = "1"
    timeout_value = (
        _command_timeout_seconds() if timeout_seconds is None else float(timeout_seconds)
    )
    if timeout_value <= 0:
        raise RuntimeError(f"INVALID_COMMAND_TIMEOUT:{timeout_value}")

    proc = subprocess.Popen(
        args,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=(os.name == "posix"),
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_value)
    except subprocess.TimeoutExpired:
        stdout, stderr = _terminate_process_tree(proc)
        if stdout:
            sys.stdout.write(stdout)
        if stderr:
            sys.stderr.write(stderr)
        raise RuntimeError(
            f"COMMAND_TIMEOUT:{' '.join(args)}:timeout_seconds={timeout_value:g}"
        )

    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)
    if proc.returncode != 0:
        raise RuntimeError(
            f"COMMAND_FAILED:{' '.join(args)}:returncode={proc.returncode}"
        )


def _verify_collection(sport: str, request_started: datetime) -> dict:
    report = read_json(COLLECTION_REPORT)
    ts = parse_ts(str(report.get("timestamp_utc") or ""))
    if ts is None or ts < request_started:
        raise RuntimeError(f"STALE_COLLECTION_REPORT:{sport}")
    if report.get("status") == "FAILED":
        raise RuntimeError(f"COLLECTION_FAILED:{sport}")
    reported_sports = report.get("sports")
    if reported_sports != [sport]:
        raise RuntimeError(
            f"COLLECTION_SCOPE_MISMATCH:expected={[sport]}:actual={reported_sports}"
        )
    return report


def _verify_prediction(sport: str, request_started: datetime) -> dict:
    report = read_json(PREDICTION_REPORT)
    ts = parse_ts(str(report.get("generated_at_utc") or ""))
    if ts is None or ts < request_started:
        raise RuntimeError(f"STALE_PREDICTION_REPORT:{sport}")

    sports = report.get("sports")
    if not isinstance(sports, list) or len(sports) != 1:
        raise RuntimeError(f"PREDICTION_SCOPE_MISMATCH:{sport}")

    item = sports[0]
    if not isinstance(item, dict) or item.get("sport") != sport:
        raise RuntimeError(f"PREDICTION_SCOPE_MISMATCH:{sport}")

    return report



def verify_latest_main() -> str:
    """Require this checkout to be exactly the current public main revision."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    if head.returncode != 0:
        raise RuntimeError("CURRENT_HEAD_UNAVAILABLE")
    current = head.stdout.strip()
    remote = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if remote.returncode != 0:
        raise RuntimeError("REMOTE_MAIN_UNAVAILABLE")
    remote_sha = remote.stdout.strip().split()[0] if remote.stdout.strip() else ""
    if not remote_sha or remote_sha != current:
        raise RuntimeError(
            f"STALE_CODE_CHECKOUT:current={current}:remote_main={remote_sha}"
        )
    return current

def request_latest(
    sports: list[str] | None = None,
    days_back: int = 30,
    days_forward: int = 7,
    lead_minutes: int = 60,
    min_lead_minutes: int | None = None,
    max_lead_minutes: int | None = None,
    prediction_origin: str = "ON_DEMAND_REQUEST",
) -> dict:
    main_sha = verify_latest_main()
    policy = read_json(FRESHNESS_PATH)
    if policy.get("refresh_before_every_prediction_request") is not True:
        raise RuntimeError("FRESHNESS_POLICY_REFRESH_DISABLED")
    if policy.get("reuse_stored_prediction_output") is not False:
        raise RuntimeError("FRESHNESS_POLICY_ALLOWS_STALE_REUSE")

    scope = active_scope()
    requested = list(sports or scope)
    invalid = sorted(set(requested) - set(scope))
    if invalid:
        raise RuntimeError(f"OUT_OF_SCOPE:{','.join(invalid)}")

    if not 5 <= int(lead_minutes) <= 180:
        raise RuntimeError("INVALID_LEAD_MINUTES:must_be_between_5_and_180")
    if min_lead_minutes is None:
        min_lead_minutes = max(5, int(lead_minutes) - 15)
    if max_lead_minutes is None:
        max_lead_minutes = min(180, int(lead_minutes) + 15)
    if int(min_lead_minutes) > int(max_lead_minutes):
        raise RuntimeError("INVALID_LEAD_WINDOW:min_greater_than_max")
    request_started = utc_now()
    request_id = request_started.strftime("%Y%m%dT%H%M%S.%fZ")
    archive_dir = ARCHIVE_ROOT / request_id
    archive_dir.mkdir(parents=True, exist_ok=False)

    reports = []
    try:
        for sport in requested:
            _run(
                [
                    sys.executable,
                    "-m",
                    "src.seven_sport_production",
                    "--sport",
                    sport,
                    "--days-back",
                    str(int(days_back)),
                    "--days-forward",
                    str(int(days_forward)),
                ],
                force_refresh=True,
                timeout_seconds=_command_timeout_seconds(),
            )
            collection = _verify_collection(sport, request_started)

            _run(
                [
                    sys.executable,
                    "-m",
                    "src.future_predictor",
                    "--sport",
                    sport,
                    "--lead-minutes",
                    str(int(lead_minutes)),
                    "--min-lead-minutes",
                    str(int(min_lead_minutes)),
                    "--max-lead-minutes",
                    str(int(max_lead_minutes)),
                    "--target-scope-only",
                    "--prediction-origin",
                    prediction_origin,
                ],
                timeout_seconds=_command_timeout_seconds(),
            )
            prediction = _verify_prediction(sport, request_started)

            (archive_dir / f"{sport}_collection.json").write_text(
                json.dumps(collection, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (archive_dir / f"{sport}_prediction.json").write_text(
                json.dumps(prediction, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            reports.append(
                {
                    "sport": sport,
                    "collection_timestamp_utc": collection.get("timestamp_utc"),
                    "prediction_generated_at_utc": prediction.get("generated_at_utc"),
                    "target_lead_minutes": int(lead_minutes),
                    "prediction_origin": prediction_origin,
                    "stored_prediction_reused": False,
                }
            )
    except Exception:
        # The archive is retained as failure evidence; no previous prediction
        # file is returned as a fallback.
        failure = {
            "request_started_at_utc": request_started.isoformat(),
            "source_git_commit_sha": main_sha,
            "status": "FAIL_CLOSED",
            "sports": requested,
            "stored_prediction_reused": False,
        }
        (archive_dir / "request_failure.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        raise

    manifest = {
        "request_id": request_id,
        "source_git_commit_sha": main_sha,
        "request_started_at_utc": request_started.isoformat(),
        "completed_at_utc": utc_now().isoformat(),
        "status": "FRESH_REQUEST_VERIFIED",
        "active_scope": scope,
        "sports": reports,
        "target_lead_minutes": int(lead_minutes),
        "min_lead_minutes": int(min_lead_minutes),
        "max_lead_minutes": int(max_lead_minutes),
        "prediction_origin": prediction_origin,
        "stored_prediction_reused": False,
        "policy": "fresh-prediction-request-v1",
        "archive_dir": str(archive_dir.relative_to(ROOT)),
    }
    (archive_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh current data and produce a verified fresh prediction."
    )
    parser.add_argument("--sport", action="append", help="Active-scope sport; repeatable.")
    parser.add_argument("--days-back", type=int, default=30)
    parser.add_argument("--days-forward", type=int, default=7)
    parser.add_argument("--lead-minutes", type=int, default=60)
    parser.add_argument("--min-lead-minutes", type=int, default=None)
    parser.add_argument("--max-lead-minutes", type=int, default=None)
    parser.add_argument(
        "--prediction-origin",
        choices=["AUTOMATED_SCHEDULE", "ON_DEMAND_REQUEST", "TIMING_SHADOW"],
        default="ON_DEMAND_REQUEST",
    )
    args = parser.parse_args()

    manifest = request_latest(
        sports=args.sport,
        days_back=args.days_back,
        days_forward=args.days_forward,
        lead_minutes=args.lead_minutes,
        min_lead_minutes=args.min_lead_minutes,
        max_lead_minutes=args.max_lead_minutes,
        prediction_origin=args.prediction_origin,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
