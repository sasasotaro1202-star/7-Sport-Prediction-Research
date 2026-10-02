"""Regression tests for the canonical fresh-prediction request contract."""

from pathlib import Path
import json
import signal
import subprocess
from unittest.mock import patch

from src import latest_prediction


ROOT = Path(__file__).resolve().parents[1]



class _TimedOutProcess:
    pid = 4321
    returncode = -15

    def __init__(self):
        self.timeouts = []
        self.signals = []
        self.communicate_calls = 0

    def communicate(self, timeout=None):
        self.timeouts.append(timeout)
        self.communicate_calls += 1
        if self.communicate_calls == 1:
            raise subprocess.TimeoutExpired(["fake"], timeout)
        return ("partial stdout\\n", "partial stderr\\n")

    def send_signal(self, sig):
        self.signals.append(sig)


def test_timeout_is_bounded_and_fail_closed():
    fake = _TimedOutProcess()
    with (
        patch.object(latest_prediction.subprocess, "Popen", return_value=fake) as popen,
        patch.object(latest_prediction.os, "getpgid", return_value=fake.pid),
        patch.object(latest_prediction.os, "killpg") as killpg,
    ):
        try:
            latest_prediction._run(["python", "-c", "sleep"], timeout_seconds=1.0)
        except RuntimeError as exc:
            assert str(exc) == "COMMAND_TIMEOUT:python -c sleep:timeout_seconds=1"
        else:
            raise AssertionError("timeout must fail closed")

    assert popen.call_args.kwargs["start_new_session"] is True
    assert fake.timeouts == [1.0, latest_prediction.TERMINATION_GRACE_SECONDS]
    assert killpg.call_args_list[0].args == (fake.pid, signal.SIGTERM)
    assert killpg.call_args_list[0].args[1] == signal.SIGTERM
    assert fake.communicate_calls == 2
    print("LATEST_PREDICTION_TIMEOUT=PASS")


def main():
    policy = json.loads(
        (ROOT / "config/PREDICTION_FRESHNESS_POLICY.json").read_text(encoding="utf-8")
    )
    scope = json.loads(
        (ROOT / "config/PROJECT_SCOPE_POLICY.json").read_text(encoding="utf-8")
    )
    src = (ROOT / "src/latest_prediction.py").read_text(encoding="utf-8")

    assert policy["refresh_before_every_prediction_request"] is True
    assert policy["reuse_stored_prediction_output"] is False
    assert policy["stale_output_action"] == "FAIL_CLOSED"

    active = scope["active_prediction_scope"]
    assert active
    assert "soccer" not in active
    assert "baseball" not in active

    # The canonical entrypoint must refresh first and infer second.
    collect_pos = src.index("src.seven_sport_production")
    predict_pos = src.index("src.future_predictor")
    assert collect_pos < predict_pos

    required = (
        "request_started_at_utc",
        "STALE_COLLECTION_REPORT",
        "STALE_PREDICTION_REPORT",
        "COLLECTION_FAILED",
        "OUT_OF_SCOPE",
        "stored_prediction_reused",
        "FRESH_REQUEST_VERIFIED",
        "force_refresh=True",
        "V45_FORCE_REFRESH",
        "verify_latest_main",
        "STALE_CODE_CHECKOUT",
        "REMOTE_MAIN_UNAVAILABLE",
        "V45_LATEST_PREDICTION_COMMAND_TIMEOUT_SECONDS",
        "COMMAND_TIMEOUT",
        "--lead-minutes",
        "--lead-tolerance-minutes",
        "requested_lead_minutes",
        "effective_lead_window_minutes",
        "start_new_session",
        "_terminate_process_tree",
    )
    for marker in required:
        assert marker in src, marker

    # Stored prediction output is verification evidence only, never a stale fallback.
    assert "PREDICTION_REPORT" in src
    assert "reuse_stored_prediction_output" in src

    test_timeout_is_bounded_and_fail_closed()
    print("LATEST_PREDICTION_CONTRACT=PASS")


if __name__ == "__main__":
    main()
