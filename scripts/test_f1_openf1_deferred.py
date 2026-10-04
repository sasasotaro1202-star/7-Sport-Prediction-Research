#!/usr/bin/env python3
"""Regression tests for explicit OpenF1 authentication-driven PIT deferral."""

from src.f1_openf1_backfill import _all_auth_deferred


def main() -> int:
    auth_401 = [
        {"year": 2023, "stage": "sessions", "http_status": 401, "error": "401"},
        {"year": 2024, "stage": "sessions", "http_status": 401, "error": "401"},
    ]
    assert _all_auth_deferred(auth_401, total=0, skipped=0)

    auth_403 = [
        {"year": 2023, "stage": "sessions", "http_status": 403, "error": "403"},
    ]
    assert _all_auth_deferred(auth_403, total=0, skipped=0)

    mixed = [
        {"year": 2023, "stage": "sessions", "http_status": 401, "error": "401"},
        {"year": 2024, "stage": "sessions", "http_status": 500, "error": "500"},
    ]
    assert not _all_auth_deferred(mixed, total=0, skipped=0)

    unknown = [
        {"year": 2023, "stage": "sessions", "error": "connection reset"},
    ]
    assert not _all_auth_deferred(unknown, total=0, skipped=0)

    assert not _all_auth_deferred(auth_401, total=1, skipped=0)
    assert not _all_auth_deferred(auth_401, total=0, skipped=1)
    assert not _all_auth_deferred([], total=0, skipped=0)

    print("F1 OpenF1 deferred-auth classification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
