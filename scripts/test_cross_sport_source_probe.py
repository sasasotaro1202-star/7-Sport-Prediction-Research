from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from src import cross_sport_source_probe as probe_mod


class _FakeResponse:
    status = 200

    def __init__(self, payload: object, url: str = "https://example.test/final") -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self._url = url

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url


def main() -> int:
    assert "{date}" in probe_mod.PROBES["sofascore"]["rizin"]
    assert "{date}" in probe_mod.PROBES["sofascore"]["boxing"]

    with patch.object(
        probe_mod.urllib.request,
        "urlopen",
        return_value=_FakeResponse({"events": [1]}),
    ) as mocked:
        result = probe_mod.probe("https://example.test/{date}")
        mocked.assert_called_once()
        called_url = mocked.call_args.args[0].full_url
        assert called_url.endswith(probe_mod.PROBE_DATE)
        assert result["ok"] is True
        assert result["json_parseable"] is True
        assert result["body_shape"] == "dict"

    with patch.object(
        probe_mod.urllib.request,
        "urlopen",
        return_value=_FakeResponse({"status": "failure", "message": "invalid api key"}),
    ):
        result = probe_mod.probe("https://example.test/{date}")
        assert result["ok"] is False
        assert result["error_signal"] == "json_failure_status"

    error = HTTPError(
        "https://example.test/fail",
        503,
        "service unavailable",
        hdrs=None,
        fp=BytesIO(b""),
    )
    with patch.object(probe_mod.urllib.request, "urlopen", side_effect=error):
        result = probe_mod.probe("https://example.test/{date}")
        assert result["ok"] is False
        assert result["status_code"] == 503
        assert result["error"] == "HTTPError:503"

    print("CROSS_SPORT_SOURCE_PROBE_LOGIC=PASS")
    print("CROSS_SPORT_SOURCE_PROBE_DYNAMIC_DATE=PASS")
    print("CROSS_SPORT_SOURCE_PROBE_HTTP_ERROR=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
