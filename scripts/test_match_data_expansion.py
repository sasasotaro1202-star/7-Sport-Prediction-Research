#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.match_data_expansion import (
    _exact_for_cutoff,
    parse_bleague_detail,
    parse_jsonld_event,
    parse_page_metadata,
    parse_vlr_match_detail,
    _summarize_run_status,
)


BLEAGUE_HTML = """
<html>
  <body>
    <h1>りそなグループ B.LEAGUE 2026-27 B.LEAGUE PREMIER リーグ戦</h1>
    <div>千葉J</div>
    <div>B.PREMIER｜東地区 2位</div>
    <div>千葉県｜ららアリ</div>
    <div>19:05 TIP OFF</div>
    <div>VS</div>
    <div>島根</div>
    <div>B.PREMIER｜西地区 4位</div>
    <div>会場：LaLa arena TOKYO-BAY</div>
    <div>放送予定</div>
    <a>バスケットLIVE</a>
    <a>BS10</a>
    <section>
      <h2>シーズン成績</h2>
      <div>2勝-1敗</div>
      <div>1勝-2敗</div>
      <div>千葉J 島根</div>
      <div>102.3点</div>
      <div>PPG平均得点数</div>
      <div>82.3点</div>
      <div>43.1%</div>
      <div>FG%フィールドゴール成功率</div>
      <div>42.2%</div>
      <div>27.7%</div>
      <div>3Fg%3Pシュート成功率</div>
      <div>34.7%</div>
      <div>74.6%</div>
      <div>ft%フリースロー成功率</div>
      <div>74.5%</div>
      <div>48.0本</div>
      <div>RPG平均トータルリバウンド数</div>
      <div>42.0本</div>
      <div>20.7本</div>
      <div>APG平均アシスト数</div>
      <div>15.7本</div>
      <div>5.7本</div>
      <div>BPG平均ブロックショット数</div>
      <div>5.0本</div>
      <div>5.0本</div>
      <div>SPG平均スティール数</div>
      <div>8.3本</div>
    </section>
  </body>
</html>
"""



VLR_HTML = """
<a href="/event/2281/valorant-champions-2026">Valorant Champions 2026</a>
<div>Group Stage: Winner's (B)</div>
<div>Saturday, September 30</div>
<div>Patch 13.05</div>
<div>Team Vitality</div>
<div>3d 8h</div>
<div>–</div>
<div>Bo3</div>
<div>LOUD</div>
<div>Betting</div>
<div>Team Vitality VIT 2.16 vs 1.63 LOUD LOUD Pre-match</div>
<div>Head-to-head</div>
<h1>Team Vitality vs. LOUD</h1>
"""

JSONLD_HTML = """
<script type="application/ld+json">
{
  "@type": "SportsEvent",
  "name": "Example Match",
  "startDate": "2026-10-10T12:00:00Z",
  "eventStatus": "EventScheduled",
  "location": {
    "@type": "Place",
    "name": "Example Arena",
    "address": {
      "@type": "PostalAddress",
      "streetAddress": "1-2-3 Example",
      "addressLocality": "Fukuoka",
      "addressRegion": "Fukuoka",
      "addressCountry": "JP"
    }
  },
  "organizer": {"@type": "Organization", "name": "Example League"},
  "homeTeam": {"@type": "SportsTeam", "name": "Home"},
  "awayTeam": {"@type": "SportsTeam", "name": "Away"}
}
</script>
"""


def main() -> int:
    data = parse_bleague_detail(BLEAGUE_HTML)
    assert data["venue_name"] == "LaLa arena TOKYO-BAY"
    assert data["tipoff"] == "19:05"
    assert data["competition"] == "B.PREMIER"
    assert data["team_records"] == [(2, 1), (1, 2)]
    assert data["standings"] == [2, 4]
    assert data["broadcasts"] == ["バスケットLIVE", "BS10"]
    assert data["season_metrics"]["PPG"] == [102.3, 82.3]
    assert data["season_metrics"]["FG_PCT"] == [43.1, 42.2]
    assert data["season_metrics"]["3FG_PCT"] == [27.7, 34.7]
    assert data["season_metrics"]["FT_PCT"] == [74.6, 74.5]
    assert data["season_metrics"]["RPG"] == [48.0, 42.0]
    assert data["season_metrics"]["APG"] == [20.7, 15.7]
    assert data["season_metrics"]["BPG"] == [5.7, 5.0]
    assert data["season_metrics"]["SPG"] == [5.0, 8.3]

    cutoff = datetime(2026, 10, 10, 11, 0, tzinfo=timezone.utc)
    event_time = cutoff + timedelta(minutes=60)
    exact, available_at = _exact_for_cutoff(
        cutoff - timedelta(seconds=1),
        event_time,
        lead_minutes=60,
    )
    assert exact is True
    assert available_at is not None

    late_exact, late_available = _exact_for_cutoff(
        cutoff + timedelta(seconds=1),
        event_time,
        lead_minutes=60,
    )
    assert late_exact is False
    assert late_available is None


    vlr = parse_vlr_match_detail(VLR_HTML)
    assert vlr["patch"] == "13.05"
    assert vlr["format"] == "Bo3"
    assert vlr["event_links"] == ["Valorant Champions 2026"]
    assert vlr["has_pre_match_betting"] is True
    assert vlr["pre_match_odds"] == [2.16, 1.63]
    assert len(vlr["pre_match_betting_text"]) == 1

    meta = parse_page_metadata(
        VLR_HTML.replace(
            '<a href="/event/2281/valorant-champions-2026">',
            '<link rel="canonical" href="https://www.vlr.gg/753451/" /><title>VIT vs LOUD</title><meta name="description" content="Match preview">\\n<a href="/event/2281/valorant-champions-2026">'
        )
    )
    assert meta["title"] == "VIT vs LOUD"
    assert meta["description"] == "Match preview"
    assert meta["canonical_url"] == "https://www.vlr.gg/753451/"
    assert meta["h1"] == "Team Vitality vs. LOUD"

    assert _summarize_run_status(0, 0, 0, 0, 0) == "NO_CANDIDATE_EVENTS"
    assert _summarize_run_status(2, 1, 0, 1, 0) == "DEGRADED"
    assert _summarize_run_status(2, 1, 0, 0, 1) == "DEGRADED"
    assert _summarize_run_status(2, 0, 2, 0, 0) == "CACHE_FRESH"
    assert _summarize_run_status(2, 2, 0, 0, 0) == "OK"

    event = parse_jsonld_event(JSONLD_HTML)
    assert event["name"] == "Example Match"
    assert event["venue_name"] == "Example Arena"
    assert event["venue_city"] == "Fukuoka"
    assert event["venue_region"] == "Fukuoka"
    assert event["venue_country"] == "JP"
    assert event["organizer"] == "Example League"
    assert event["teams"] == ["Home", "Away"]

    print("MATCH_DATA_EXPANSION_PARSER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
