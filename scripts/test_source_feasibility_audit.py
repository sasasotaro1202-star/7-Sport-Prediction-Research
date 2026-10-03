#!/usr/bin/env python3
from __future__ import annotations

from types import SimpleNamespace

from src.source_feasibility_audit import build_report, probe_source


class FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self._text = text
        self.content = text.encode("utf-8")

    @property
    def text(self):
        return self._text


class FakeRequests:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text

    def get(self, *args, **kwargs):
        return FakeResponse(self.status_code, self.text)


def main() -> int:
    import src.source_feasibility_audit as audit

    original = audit.requests.get
    try:
        audit.requests.get = FakeRequests(
            200, "<html>Upcoming matches Completed matches FIBA</html>"
        ).get
        row = probe_source(
            {
                "source_id": "test",
                "name": "test",
                "url": "https://example.invalid",
                "required_signals": ["Upcoming matches", "Completed matches", "FIBA"],
                "capabilities": ["schedule"],
                "critical": True,
                "pit_status": "UNPROVEN",
            }
        )
        assert row["status"] == "REACHABLE_WITH_EXPECTED_SIGNALS"
        assert row["reachable"] is True
        assert row["pit_status"] == "UNPROVEN"

        audit.requests.get = FakeRequests(200, "<html>hello</html>").get
        row = probe_source(
            {
                "source_id": "test",
                "name": "test",
                "url": "https://example.invalid",
                "required_signals": ["Missing signal"],
                "capabilities": ["schedule"],
                "critical": True,
                "pit_status": "UNPROVEN",
            }
        )
        assert row["status"] == "REACHABLE_SIGNALS_PARTIAL"

        policy = {
            "active_sports": {
                "sport_a": [
                    {
                        "source_id": "a",
                        "name": "a",
                        "url": "https://example.invalid",
                        "required_signals": ["OK"],
                        "critical": True,
                        "pit_status": "UNPROVEN",
                    }
                ],
                "sport_b": [
                    {
                        "source_id": "b",
                        "name": "b",
                        "url": "https://example.invalid",
                        "required_signals": ["OK"],
                        "critical": True,
                        "pit_status": "UNPROVEN",
                    }
                ],
            }
        }
        audit.requests.get = FakeRequests(200, "OK").get
        report = build_report(policy, timeout=5)
        assert report["status"] == "PASS"
        assert report["sport_status"]["sport_a"]["status"] == "SOURCE_REACHABLE"
        assert report["sport_status"]["sport_a"]["critical_source_reachable"] is True
        assert report["interpretation"]["pit_status"] == "UNPROVEN unless independently backed by source-availability evidence"
    finally:
        audit.requests.get = original

    print("SOURCE_FEASIBILITY_AUDIT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
