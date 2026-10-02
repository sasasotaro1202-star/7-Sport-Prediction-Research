from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import requests

import src.seven_sport_production as mod
from src.seven_sport_production import HTTP


class FakeResponse:
    def __init__(self, status_code=200, text="OK"):
        self.status_code = status_code
        self.text = text
        self.headers = {"Retry-After": "0.01"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


def main() -> int:
    old_timeout = os.environ.get("V45_HTTP_TIMEOUT")
    old_retries = os.environ.get("V45_HTTP_RETRIES")
    os.environ["V45_HTTP_TIMEOUT"] = "45"
    os.environ["V45_HTTP_RETRIES"] = "4"
    try:
        with tempfile.TemporaryDirectory() as td:
            h = HTTP()
            h.cache_dir = Path(td)
            calls = []
            sequence = [
                requests.exceptions.ReadTimeout("slow"),
                FakeResponse(503, "busy"),
                FakeResponse(200, "fresh"),
            ]

            original = mod.requests.get

            def fake_get(*args, **kwargs):
                calls.append(kwargs)
                item = sequence.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

            mod.requests.get = fake_get
            try:
                text, _, _ = h.get("https://example.invalid/resilient", use_cache=False)
            finally:
                mod.requests.get = original

            assert text == "fresh"
            assert len(calls) == 3
            assert calls[0]["timeout"] == (15, 45.0)
            assert calls[1]["timeout"] == (15, 45.0)
            assert h.retries == 4

            cached = json.loads(
                h._cache_path("https://example.invalid/resilient").read_text(
                    encoding="utf-8"
                )
            )
            assert cached["text"] == "fresh"
            assert cached["status"] == 200
    finally:
        if old_timeout is None:
            os.environ.pop("V45_HTTP_TIMEOUT", None)
        else:
            os.environ["V45_HTTP_TIMEOUT"] = old_timeout
        if old_retries is None:
            os.environ.pop("V45_HTTP_RETRIES", None)
        else:
            os.environ["V45_HTTP_RETRIES"] = old_retries

    print("HTTP_REQUEST_RESILIENCE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
