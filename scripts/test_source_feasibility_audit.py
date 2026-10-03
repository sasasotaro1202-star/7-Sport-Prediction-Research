#!/usr/bin/env python3
from __future__ import annotations


class FakeResponse:
    def __init__(self, status_code: int, text: str, payload=None, content_type="text/html"):
        self.status_code = status_code
        self._text = text
        self._payload = payload
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}

    @property
    def text(self):
        return self._text

    def json(self):
        if self._payload is not None:
            return self._payload
        raise ValueError("invalid json")


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.headers = {}

    def get(self, *args, **kwargs):
        return self.response


def main() -> int:
    import src.source_feasibility_audit as audit

    original_session = audit.requests.Session
    try:
        # Mock the same Session API used by production code. The prior test
        # patched requests.get(), which did not intercept Session().get() and
        # therefore could accidentally perform live network calls.
        audit.requests.Session = lambda: FakeSession(
            FakeResponse(
                200,
                "<html><span>Upcoming</span> matches "
                "<span>Completed</span> matches FIBA</html>",
            )
        )
        row = audit.probe_source(
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

        audit.requests.Session = lambda: FakeSession(
            FakeResponse(200, "<html><span>hello</span></html>")
        )
        row = audit.probe_source(
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

        audit.requests.Session = lambda: FakeSession(
            FakeResponse(
                200,
                '{"total": 2, "data": [{"id": "e1", "name": "UFC 1", "date": "2026-01-01"}]}',
                payload={
                    "total": 2,
                    "limit": 1,
                    "offset": 0,
                    "data": [{"id": "e1", "name": "UFC 1", "date": "2026-01-01"}],
                },
                content_type="application/json",
            )
        )
        row = audit.probe_source(
            {
                "source_id": "json-test",
                "name": "json-test",
                "url": "https://example.invalid/api/events",
                "probe_mode": "json_collection",
                "minimum_records": 1,
                "required_json_key_groups": [["id"], ["name"], ["date", "event_date"]],
                "required_signals": [],
                "critical": True,
                "pit_status": "UNPROVEN",
            }
        )
        assert row["status"] == "REACHABLE_WITH_EXPECTED_SIGNALS"
        assert row["data_shape"]["record_count"] == 1
        assert row["data_shape"]["valid"] is True

        # A valid JSON envelope with no records must not be accepted as usable.
        audit.requests.Session = lambda: FakeSession(
            FakeResponse(
                200,
                '{"total": 0, "data": []}',
                payload={"total": 0, "data": []},
                content_type="application/json",
            )
        )
        row = audit.probe_source(
            {
                "source_id": "empty-json",
                "name": "empty-json",
                "url": "https://example.invalid/api/events",
                "probe_mode": "json_collection",
                "minimum_records": 1,
                "required_json_key_groups": [["id"]],
                "required_signals": [],
                "critical": True,
                "pit_status": "UNPROVEN",
            }
        )
        assert row["status"] == "REACHABLE_SIGNALS_PARTIAL"
        assert row["data_shape"]["valid"] is False

        audit.requests.Session = lambda: FakeSession(
            FakeResponse(
                200,
                '<html>'
                '<a class="match-item" href="/12345/team-a-vs-team-b/">Upcoming relative</a>'
                '<a class="match-item" href="https://www.vlr.gg/67890/team-c-vs-team-d/">Upcoming absolute</a>'
                '</html>',
            )
        )
        row = audit.probe_source(
            {
                "source_id": "vlr-structure",
                "name": "VLR",
                "url": "https://example.invalid/matches",
                "required_patterns": [r'href=["\']?(?:https?://(?:www\.)?vlr\.gg)?/\d+/[^"\'?#\s]+', r"match-item"],
                "required_signals": [],
                "critical": True,
                "pit_status": "UNPROVEN",
            }
        )
        assert row["status"] == "REACHABLE_WITH_EXPECTED_SIGNALS"
        assert row["patterns_missing"] == []

        # Exercise the repository's actual VLR policy pattern, not only a copied test regex.
        configured = audit._load_policy()["active_sports"]["valorant"][0]
        audit.requests.Session = lambda: FakeSession(
            FakeResponse(
                200,
                '<html><a class="match-item" href="/732644/bar-a-esports-gc-vs-giantx-gc-game-changers-2026-emea-stage-3-sf">Upcoming</a></html>',
            )
        )
        row = audit.probe_source(
            {
                "source_id": configured["source_id"],
                "name": configured["name"],
                "url": configured["url"],
                "required_patterns": configured["required_patterns"],
                "required_signals": configured.get("required_signals", []),
                "critical": configured["critical"],
                "pit_status": configured["pit_status"],
            }
        )
        assert row["status"] == "REACHABLE_WITH_EXPECTED_SIGNALS"
        assert row["patterns_missing"] == []

        # A bare number elsewhere in the page must not satisfy the VLR link contract.
        audit.requests.Session = lambda: FakeSession(
            FakeResponse(200, '<html><div class="match-item">2026 season</div><a href="https://evil.example/12345/not-vlr/">x</a></html>')
        )
        row = audit.probe_source(
            {
                "source_id": "vlr-negative",
                "name": "VLR",
                "url": "https://example.invalid/matches",
                "required_patterns": [r'href=["\']?(?:https?://(?:www\.)?vlr\.gg)?/\d+/[^"\'?#\s]+', r"match-item"],
                "required_signals": [],
                "critical": True,
                "pit_status": "UNPROVEN",
            }
        )
        assert row["status"] == "REACHABLE_SIGNALS_PARTIAL"
        assert row["patterns_missing"] == [r'href=["\']?(?:https?://(?:www\.)?vlr\.gg)?/\d+/[^"\'?#\s]+']

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
        audit.requests.Session = lambda: FakeSession(FakeResponse(200, "OK"))
        report = audit.build_report(policy, timeout=5)
        assert report["status"] == "PASS"
        assert report["sport_status"]["sport_a"]["status"] == "SOURCE_REACHABLE"
        assert report["sport_status"]["sport_a"]["critical_source_reachable"] is True
        assert report["interpretation"]["pit_status"] == "UNPROVEN unless independently backed by source-availability evidence."
    finally:
        audit.requests.Session = original_session

    print("SOURCE_FEASIBILITY_AUDIT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
