#!/usr/bin/env python3
from __future__ import annotations

from src.seven_sport_production import _vlr_match_urls


def main() -> int:
    html = """
    <a class="match-item" href="/732644/bar-a-esports-gc-vs-giantx-gc-game-changers-2026-emea-stage-3-sf">
      relative
    </a>
    <a class="match-item" href="https://www.vlr.gg/67890/team-c-vs-team-d-event">
      absolute
    </a>
    <a href="https://evil.example/12345/not-vlr">evil</a>
    <a href="/static/12345/script.js">static</a>
    <a href="/12345/no-slug?x=1">query</a>
    """
    rows = _vlr_match_urls(html)
    assert rows == [
        "https://www.vlr.gg/732644/bar-a-esports-gc-vs-giantx-gc-game-changers-2026-emea-stage-3-sf",
        "https://www.vlr.gg/67890/team-c-vs-team-d-event",
    ]
    assert all("evil.example" not in row for row in rows)
    print("VLR_MATCH_URLS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
