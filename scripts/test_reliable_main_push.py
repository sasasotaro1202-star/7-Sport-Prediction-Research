#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.reliable_main_push import backoff_seconds, classify_push_failure


def test_transient_github_error() -> None:
    assert classify_push_failure("remote: Internal Server Error") == "TRANSIENT"


def test_transient_transport_error() -> None:
    assert classify_push_failure("fatal: the remote end hung up unexpectedly") == "TRANSIENT"


def test_nontransient_rejection() -> None:
    assert classify_push_failure("! [rejected] HEAD -> main (non-fast-forward)") == "NONTRANSIENT"


def test_unknown_is_fail_closed() -> None:
    assert classify_push_failure("some unfamiliar git failure") == "UNKNOWN"


def test_deterministic_backoff() -> None:
    assert [backoff_seconds(i, 3, 30) for i in range(1, 7)] == [3, 6, 12, 24, 30, 30]


if __name__ == "__main__":
    test_transient_github_error()
    test_transient_transport_error()
    test_nontransient_rejection()
    test_unknown_is_fail_closed()
    test_deterministic_backoff()
    print("reliable_main_push tests passed")
