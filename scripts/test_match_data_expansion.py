#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

from src.match_data_expansion import (
    _exact_for_cutoff,
    parse_bleague_detail,
    parse_fiba_game_detail,
    parse_jsonld_event,
    parse_rizin_detail,
    parse_ufcstats_detail,
    parse_volleyball_detail,
    select_events,
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



FIBA_HTML = """
<h1>Japan</h1><h1>Philippines</h1>
<div>Group Phase · Group D</div>
<div>Japan 80 - 75 Philippines</div>
<div>Game Stats</div>
<div>FG % 41 45</div>
<div>2PT FG 54.1% 58%</div>
<div>3PT FG 22.2% 14.3%</div>
<div>FT % 95.7% 66.7%</div>
<div>Attendance 126</div>
"""

VOLLEYBALL_HTML = """
<h1>Japan vs USA</h1>
<div>Final</div>
<div>Venue: Ariake Arena</div>
<div>25-22</div>
"""

UFCSTATS_HTML = """
<h1>Example Fighter Record: 10-3-0</h1>
<div>Height: 5' 9"</div>
<div>Weight: 155 lbs.</div>
<div>Reach: 70"</div>
<div>STANCE: Orthodox</div>
<div>DOB: Jan. 02, 1995</div>
<div>SLpM: 2.48</div>
<div>Str. Acc.: 42%</div>
<div>SApM: 4.08</div>
<div>Str. Def: 53%</div>
<div>TD Avg.: 1.31</div>
<div>TD Acc.: 35%</div>
<div>TD Def.: 52%</div>
<div>Sub. Avg.: 1.1</div>
<div>Matchup Preview</div>
"""

RIZIN_HTML = """
<h1>堀江圭功 vs. 宇佐美正パトリック</h1>
<div>ルール</div>
<div>RIZIN MMAルール：5分3R（72.65kg）</div>
<div>変更のお知らせ</div>
<div>試合結果</div>
<div>2R 3分37秒 TKO</div>
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

    fiba = parse_fiba_game_detail(FIBA_HTML)
    assert fiba["game_stage"] == "Group Phase"
    assert fiba["score_a"] == 80
    assert fiba["score_b"] == 75
    assert fiba["attendance"] == 126
    assert fiba["game_stats"]["2pt_fg_pct"] == [54.1, 58.0]
    assert fiba["game_stats"]["3pt_fg_pct"] == [22.2, 14.3]
    assert fiba["game_stats"]["ft_pct"] == [95.7, 66.7]

    volleyball = parse_volleyball_detail(VOLLEYBALL_HTML)
    assert volleyball["status"] == "FINAL"
    assert volleyball["venue"] == "Ariake Arena"
    assert volleyball["score"] == [25, 22]

    ufc = parse_ufcstats_detail(UFCSTATS_HTML)
    assert ufc["height"] == """5' 9\""""
    assert ufc["weight"] == "155 lbs."
    assert ufc["reach"] == """70\""""
    assert ufc["stance"] == "Orthodox"
    assert ufc["career_stats"]["SLpM"] == 2.48
    assert ufc["career_stats"]["Str_Acc"] == 42.0
    assert ufc["career_stats"]["TD_Def"] == 52.0
    assert ufc["has_matchup_preview"] is True

    rizin = parse_rizin_detail(RIZIN_HTML)
    assert rizin["contract_weight_kg"] == 72.65
    assert rizin["change_notice"] is True
    assert rizin["round"] == 2
    assert rizin["time"] == "3:37"
    assert "TKO" in rizin["method"]


    event = parse_jsonld_event(JSONLD_HTML)
    assert event["name"] == "Example Match"
    assert event["venue_name"] == "Example Arena"
    assert event["venue_city"] == "Fukuoka"
    assert event["venue_region"] == "Fukuoka"
    assert event["venue_country"] == "JP"
    assert event["organizer"] == "Example League"
    assert event["teams"] == ["Home", "Away"]


    con = sqlite3.connect(":memory:")
    con.executescript(
        """
        CREATE TABLE event(
            event_id TEXT PRIMARY KEY,
            sport TEXT,
            event_time_utc TEXT,
            event_type TEXT,
            status TEXT
        );
        CREATE TABLE event_participant(
            event_id TEXT,
            participant_id TEXT,
            team_id TEXT,
            side TEXT,
            role TEXT,
            source_url TEXT
        );
        """
    )
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    con.execute(
        "INSERT INTO event VALUES(?,?,?,?,?)",
        ("evt-1", "ufc", future, "match", "SCHEDULED"),
    )
    con.execute(
        "INSERT INTO event_participant VALUES(?,?,?,?,?,?)",
        ("evt-1", "p1", None, "A", None, "https://ufcstats.com/event-details/example"),
    )
    rows = select_events(con, "ufc", horizon_days=1, max_events=10)
    assert len(rows) == 1
    assert rows[0][5] == "https://ufcstats.com/event-details/example"
    con.close()

    # A selected future event with a fetch error must be degraded even when
    # another selected event was successfully enriched.
    import src.match_data_expansion as mde
    original_select_events = mde.select_events
    original_enrich_one = mde.enrich_one
    original_connect = mde.connect

    class _FakeCon:
        def execute(self, query, params=()):
            if "SELECT COUNT(*) FROM match_stats" in query:
                return type("_R", (), {"fetchone": lambda self: (0,)})()
            if "FROM source_snapshot" in query:
                return type("_R", (), {"fetchone": lambda self: None})()
            raise AssertionError(f"unexpected query: {query}")
        def commit(self):
            return None
        def close(self):
            return None

    def fake_connect():
        return _FakeCon()

    def fake_select_events(con, sport, horizon_days=14, max_events=40):
        return [
            {"event_id": "ok-event", "sport": sport, "event_time_utc": future,
             "event_type": "match", "status": "SCHEDULED",
             "source_url": "https://example/ok"},
            {"event_id": "error-event", "sport": sport, "event_time_utc": future,
             "event_type": "match", "status": "SCHEDULED",
             "source_url": "https://example/error"},
        ]

    def fake_enrich_one(con, event, lead_minutes=60):
        if event["event_id"] == "error-event":
            return {"status": "FETCH_ERROR", "event_id": event["event_id"]}
        return {"status": "OK", "event_id": event["event_id"], "written_stats": 1}

    mde.connect = fake_connect
    mde.select_events = fake_select_events
    mde.enrich_one = fake_enrich_one
    try:
        report = mde.run("ufc", horizon_days=1, max_events=2, lead_minutes=60)
        assert report["selected_events"] == 2
        assert report["processed_events"] == 2
        assert report["fetch_errors"] == 1
        assert report["status"] == "DEGRADED"
    finally:
        mde.connect = original_connect
        mde.select_events = original_select_events
        mde.enrich_one = original_enrich_one
    print("MATCH_DATA_EXPANSION_PARSER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
