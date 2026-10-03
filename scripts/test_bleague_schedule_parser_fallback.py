#!/usr/bin/env python3
from __future__ import annotations

from bs4 import BeautifulSoup

from src.basketball_cdn_backfill import (
    _fallback_competition,
    _fallback_container,
    _fallback_date,
    _fallback_names,
    _game_id,
    _normalise_href,
)


def main() -> int:
    html = """
    <section>
      <h3>10/17(土)</h3>
      <div class="match-card">
        <span>B.PREMIER</span>
        <a href="/game_detail/?ScheduleKey=506471">
          千葉J 島根 千葉県 | ららアリ 13:05 見どころ
        </a>
      </div>
    </section>
    """
    soup = BeautifulSoup(html, "lxml")
    anchor = soup.select_one("a[href*='game_detail']")
    assert anchor is not None

    href = _normalise_href(anchor.get("href"))
    assert _game_id(href) == "506471"

    container = _fallback_container(anchor)
    context = container.get_text(" ", strip=True)
    match_date = _fallback_date(anchor, container)
    assert match_date is not None
    assert match_date.group(1) == "10"
    assert match_date.group(2) == "17"

    assert _fallback_names(anchor.get_text(" ", strip=True)) == ["千葉J", "島根"]
    assert _fallback_competition(context) == "B.PREMIER"

    print("BLEAGUE_SCHEDULE_FALLBACK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
