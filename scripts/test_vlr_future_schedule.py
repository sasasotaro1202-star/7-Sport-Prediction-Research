#!/usr/bin/env python3
"""Regression tests for VALORANT current-schedule refresh and VLR event parsing."""

from __future__ import annotations

from datetime import datetime, timezone

from bs4 import BeautifulSoup

from src.seven_sport_production import (
    _vlr_event_competition_id,
    _vlr_reference_datetime,
    _vlr_event_time,
    _vlr_match_status,
    _vlr_page_plan,
)


def main() -> int:
    future_html = """
    <html>
      <head><title>JDG Esports vs. EDward Gaming | VCT 2026: China Stage 2</title></head>
      <body>
        <div class="match-header-date-item">Tuesday, August 11</div>
        <div class="match-header-link-date">9:00 AM BST</div>
        <div class="match-header-vs-note">12h 33m</div>
        <a href="/event/2286/vct-2026-china-stage-2">VCT 2026: China Stage 2</a>
        <div class="match-header-link-name">JDG Esports</div>
        <div class="match-header-link-name">EDward Gaming</div>
      </body>
    </html>
    """
    now = datetime(2026, 8, 10, 18, 0, tzinfo=timezone.utc)
    cached_retrieved = "2026-08-10T18:00:00+00:00"
    assert _vlr_reference_datetime(cached_retrieved).year == 2026

    event_time = _vlr_event_time(
        future_html,
        "https://www.vlr.gg/724631/jdg-esports-vs-edward-gaming-vct-2026-china-stage-2-lr3",
        reference_year=2026,
    )
    assert event_time == "2026-08-11T08:00:00+00:00", event_time

    soup = BeautifulSoup(future_html, "lxml")
    assert _vlr_match_status(soup, event_time, now) == "SCHEDULED"
    assert _vlr_match_status(
        soup, event_time, "2026-08-10T18:00:00+00:00"
    ) == "SCHEDULED"
    assert _vlr_event_competition_id(soup, "https://www.vlr.gg/724631/example") == "vlr:event:2286"

    completed_html = """
    <html>
      <head><title>Titan Esports Club vs. Dragon Ranger Gaming | VCT 2026: China Stage 2</title></head>
      <body>
        <div class="match-header-date-item">Monday, August 10</div>
        <div class="match-header-link-date">8:40 PM AEST</div>
        <div class="match-header-vs-note-item">final</div>
        <div class="match-header">
          <span class="event-label">Upper Final</span>
          <span class="score">2 : 1</span>
          <span>vs.</span>
        </div>
      </body>
    </html>
    """
    completed_time = _vlr_event_time(
        completed_html,
        "https://www.vlr.gg/724630/titan-esports-club-vs-dragon-ranger-gaming-vct-2026-china-stage-2-ubsf",
        reference_year=2026,
    )
    assert completed_time == "2026-08-10T10:40:00+00:00", completed_time
    assert _vlr_match_status(soup=BeautifulSoup(completed_html, "lxml"),
                             event_time=completed_time,
                             reference_now=now) == "COMPLETED"

    # A completed tab/link elsewhere on a page must not turn an upcoming match
    # into COMPLETED. The old implementation scanned the entire HTML and did
    # exactly that.
    noisy_future = future_html.replace(
        "</body>", '<div class="navigation">completed matches</div></body>'
    )
    noisy_soup = BeautifulSoup(noisy_future, "lxml")
    assert _vlr_match_status(noisy_soup, event_time, now) == "SCHEDULED"

    # Persistent historical pagination can be far beyond the first pages.
    # Every scheduled run must still refresh page 1 for upcoming events.
    assert _vlr_page_plan(1, 20) == list(range(1, 21))
    assert _vlr_page_plan(21, 40) == [1, *range(21, 41)]
    assert _vlr_page_plan(181, 20) == [1]

    print("VLR_FUTURE_SCHEDULE_CONTRACT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
