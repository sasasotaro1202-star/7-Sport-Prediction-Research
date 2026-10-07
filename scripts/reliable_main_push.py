#!/usr/bin/env python3
"""Fail-closed, retrying push of the current commit to main.

This helper is intentionally narrow: it retries transient transport/server
failures, but it never overwrites a concurrently advanced main branch.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from typing import Sequence


TRANSIENT_MARKERS = (
    "internal server error",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "request id",
    "connection reset",
    "connection aborted",
    "connection timed out",
    "timed out",
    "timeout",
    "early eof",
    "remote end hung up",
    "rpc failed",
    "sideband packet",
    "temporarily unavailable",
    "rate limit",
    "too many requests",
)

NONTRANSIENT_MARKERS = (
    "non-fast-forward",
    "non fast forward",
    "rejected",
    "protected branch",
    "permission denied",
    "authentication failed",
    "repository not found",
    "gh006",
    "gh013",
)


def run_capture(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        text=True,
        capture_output=True,
        check=False,
    )


def remote_main_sha() -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repository or "/" not in repository:
        raise RuntimeError("GITHUB_REPOSITORY is missing or invalid")
    proc = run_capture(
        ["gh", "api", f"repos/{repository}/git/ref/heads/main", "--jq", ".object.sha"]
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"REMOTE_SHA_QUERY_FAILED:{detail}")
    sha = proc.stdout.strip()
    if not sha:
        raise RuntimeError("REMOTE_SHA_QUERY_EMPTY")
    return sha


def classify_push_failure(output: str) -> str:
    text = output.lower()
    if any(marker in text for marker in NONTRANSIENT_MARKERS):
        return "NONTRANSIENT"
    if any(marker in text for marker in TRANSIENT_MARKERS):
        return "TRANSIENT"
    return "UNKNOWN"


def backoff_seconds(attempt: int, initial: int, maximum: int) -> int:
    # Deterministic exponential backoff. No jitter: the workflow itself is
    # already concurrency-controlled and reproducibility is more important.
    return min(maximum, initial * (2 ** max(0, attempt - 1)))


def verify_local_parent(expected_parent: str) -> None:
    proc = run_capture(["git", "rev-parse", "HEAD^"])
    if proc.returncode != 0:
        raise RuntimeError("LOCAL_PARENT_QUERY_FAILED")
    actual = proc.stdout.strip()
    if actual != expected_parent:
        raise RuntimeError(
            f"LOCAL_PARENT_MISMATCH expected={expected_parent} actual={actual}"
        )


def verify_remote_head(expected_head: str, attempts: int = 3, delay: float = 1.5) -> bool:
    for index in range(attempts):
        try:
            actual = remote_main_sha()
        except RuntimeError:
            actual = ""
        if actual == expected_head:
            return True
        if index + 1 < attempts:
            time.sleep(delay)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-parent", required=True)
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--initial-delay", type=int, default=3)
    parser.add_argument("--max-delay", type=int, default=30)
    args = parser.parse_args()

    if args.attempts < 1:
        raise SystemExit("--attempts must be positive")
    if args.initial_delay < 0 or args.max_delay < 0:
        raise SystemExit("backoff values must be non-negative")

    try:
        verify_local_parent(args.expected_parent)
    except RuntimeError as exc:
        print(f"RELIABLE_PUSH_FAIL_CLOSED={exc}", file=sys.stderr)
        return 2

    for attempt in range(1, args.attempts + 1):
        try:
            current = remote_main_sha()
        except RuntimeError as exc:
            if attempt >= args.attempts:
                print(f"RELIABLE_PUSH_REMOTE_QUERY_FAILED={exc}", file=sys.stderr)
                return 3
            delay = backoff_seconds(attempt, args.initial_delay, args.max_delay)
            print(
                f"RELIABLE_PUSH_RETRY attempt={attempt}/{args.attempts} "
                f"reason=remote_sha_query_failure delay={delay}s",
                flush=True,
            )
            time.sleep(delay)
            continue

        head = run_capture(["git", "rev-parse", "HEAD"]).stdout.strip()
        if head and current == head:
            print(
                f"RELIABLE_PUSH_SUCCESS already_visible attempt={attempt} head={head}",
                flush=True,
            )
            return 0
        if current != args.expected_parent:
            print(
                "RELIABLE_PUSH_STALE_MAIN "
                f"expected_parent={args.expected_parent} actual_main={current}",
                file=sys.stderr,
            )
            return 20

        proc = run_capture(["git", "push", "origin", "HEAD:main"])
        combined = "\n".join(
            part for part in (proc.stdout, proc.stderr) if part
        ).strip()

        if proc.returncode == 0:
            head = run_capture(["git", "rev-parse", "HEAD"]).stdout.strip()
            if head and verify_remote_head(head):
                print(
                    f"RELIABLE_PUSH_SUCCESS attempt={attempt} head={head}",
                    flush=True,
                )
                return 0
            classification = "POST_PUSH_UNVERIFIED"
        else:
            classification = classify_push_failure(combined)
            print(
                f"RELIABLE_PUSH_ATTEMPT_FAILED attempt={attempt}/{args.attempts} "
                f"classification={classification} rc={proc.returncode}",
                file=sys.stderr,
            )
            if combined:
                print(combined[-4000:], file=sys.stderr)
            if classification != "TRANSIENT":
                print(
                    "RELIABLE_PUSH_FAIL_CLOSED "
                    f"classification={classification}",
                    file=sys.stderr,
                )
                return 4

        if attempt >= args.attempts:
            print(
                f"RELIABLE_PUSH_EXHAUSTED classification={classification}",
                file=sys.stderr,
            )
            return 5

        delay = backoff_seconds(attempt, args.initial_delay, args.max_delay)
        print(
            f"RELIABLE_PUSH_RETRY attempt={attempt}/{args.attempts} "
            f"reason={classification} delay={delay}s",
            flush=True,
        )
        time.sleep(delay)

    return 6


if __name__ == "__main__":
    raise SystemExit(main())
