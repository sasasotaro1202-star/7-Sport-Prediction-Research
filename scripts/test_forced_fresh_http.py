"""Behavioral regression test for forced fresh HTTP retrieval."""
import json
import os
import tempfile
from pathlib import Path

from src.seven_sport_production import HTTP


class FakeResponse:
    status_code = 200
    text = "FRESH"
    headers = {"ETag": "fresh"}

    def raise_for_status(self):
        return None


def main():
    with tempfile.TemporaryDirectory() as td:
        http = HTTP()
        http.cache_dir = Path(td)
        url = "https://example.invalid/fresh"
        cp = http._cache_path(url)
        cp.write_text(
            json.dumps(
                {
                    "status": 200,
                    "text": "STALE_CACHE",
                    "retrieved_at_utc": "2000-01-01T00:00:00+00:00",
                    "headers": {},
                }
            ),
            encoding="utf-8",
        )

        text, _, _ = http.get(url, use_cache=True)
        assert text == "STALE_CACHE"

        old = os.environ.get("V45_FORCE_REFRESH")
        os.environ["V45_FORCE_REFRESH"] = "1"
        try:
            refreshed = HTTP()
            refreshed.cache_dir = Path(td)
            calls = []

            import src.seven_sport_production as mod
            original = mod.requests.get
            mod.requests.get = lambda *args, **kwargs: (
                calls.append((args, kwargs)) or FakeResponse()
            )
            try:
                text, _, headers = refreshed.get(url, use_cache=True)
            finally:
                mod.requests.get = original

            assert text == "FRESH"
            assert headers["ETag"] == "fresh"
            assert len(calls) == 1
        finally:
            if old is None:
                os.environ.pop("V45_FORCE_REFRESH", None)
            else:
                os.environ["V45_FORCE_REFRESH"] = old

    print("FORCED_FRESH_HTTP=PASS")


if __name__ == "__main__":
    main()
