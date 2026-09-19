from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from src.storage.db_v45 import connect, utcnow
from src.seven_sport_production import add_snapshot, add_stat, upsert_ep, upsert_event, upsert_participant

SPORT = "basketball"
UA = "SevenSportResearchEngine/4.6-basketball-scope-correct"
BLEAGUE_SCHEDULE = "https://www.bleague.jp/schedule/?mon={month:02d}&tab=1&year={season_year}"
BLEAGUE_RAW = "https://raw.githubusercontent.com/rintaromasuda/bleaguer/master/inst/extdata/{path}"

SEASONS = tuple(range(2016, 2027))


def iso(v):
    if not v:
        return None
    s = str(v).strip().replace("Z", "+00:00")
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d %H:%M"):
        try:
            return datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    try:
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def sid(*x):
    return hashlib.sha256("|".join("" if v is None else str(v) for v in x).encode()).hexdigest()[:32]


def clean(x):
    return re.sub(r"\s+", " ", str(x or "")).strip()


def get(url, timeout=30):
    # Network/transient failures must not silently erase an otherwise valid
    # historical partition. Retry boundedly with backoff while preserving the
    # original retrieval timestamp as the provenance observation time.
    last = None
    for attempt in range(4):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"},
                timeout=timeout,
            )
            r.raise_for_status()
            return r.text, utcnow(), r.headers
        except (requests.RequestException, TimeoutError) as exc:
            last = exc
            if attempt < 3:
                import time
                time.sleep(1.5 * (2 ** attempt))
    raise last


def parse_schedule_page(c, html, retrieved, url, season_year, month):
    soup = BeautifulSoup(html, "lxml")
    added = 0
    for li in soup.select("li.MatchList"):
        a = li.select_one("a[href*='game_detail']")
        if not a:
            continue
        href = a.get("href", "")
        if href.startswith("/"):
            href = "https://www.bleague.jp" + href
        game_id = re.search(r"ScheduleKey=(\d+)", href)
        game_id = game_id.group(1) if game_id else None
        day = clean((li.select_one(".Match_day") or li).get_text(" ", strip=True))
        tm = re.search(r"(\d{1,2}:\d{2})", day)
        start = tm.group(1) if tm else None
        md = re.search(r"(\d{1,2})/(\d{1,2})", day)
        if not md:
            continue
        y = season_year if int(md.group(1)) >= 9 else season_year + 1
        et = iso(f"{y:04d}-{int(md.group(1)):02d}-{int(md.group(2)):02d}T{start or '00:00'}:00")
        names = [clean(x.get_text(" ", strip=True)) for x in li.select(".Match_name p")]
        if len(names) < 2:
            continue
        score_nodes = [clean(x.get_text(" ", strip=True)) for x in li.select(".Match_score p")]
        scores = []
        for z in score_nodes:
            m = re.search(r"(\d+)\s*[-–]\s*(\d+)", z)
            if m:
                scores.append((float(m.group(1)), float(m.group(2))))
        round_node = li.select_one(".Match_round")
        competition = clean(round_node.get_text(" ", strip=True)) if round_node else "B.LEAGUE"
        eid = sid(SPORT, "bleague-official", game_id or href)
        eid = upsert_event(c, SPORT, f"{names[0]} vs {names[1]}", et, "bleague-official", href, "COMPLETED" if scores else "SCHEDULED", competition=competition, season=f"{season_year}-{str(season_year + 1)[-2:]}")
        p1 = upsert_participant(c, SPORT, names[0], "team")
        p2 = upsert_participant(c, SPORT, names[1], "team")
        upsert_ep(c, eid, p1, p1, "A", "match", "bleague-official", href)
        upsert_ep(c, eid, p2, p2, "B", "match", "bleague-official", href)
        if scores:
            sa, sb = scores[0]
            c.execute("""INSERT OR REPLACE INTO event_outcome
                (event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,outcome_status,source,source_url,observed_at_utc,quality_status,reason)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (eid, SPORT, p1, p2, "A" if sa > sb else "B" if sb > sa else "DRAW", sa, sb,
                 "VERIFIED", "bleague-official", href, retrieved, "PIT_REQUIRES_REPLAY", "Official B.LEAGUE schedule/result page."))
        added += 1
    add_snapshot(c, SPORT, "bleague-official", url, retrieved, None,
                 hashlib.sha256(html.encode("utf-8", "ignore")).hexdigest(), "UNVERIFIABLE")
    return added


def collect_official(c, season_years):
    total = 0
    for season_year in season_years:
        for month in range(1, 13):
            url = BLEAGUE_SCHEDULE.format(month=month, season_year=season_year)
            try:
                html, retrieved, _ = get(url)
                total += parse_schedule_page(c, html, retrieved, url, season_year, month)
            except Exception:
                continue
        c.commit()
    return total


def collect_historical_bleaguer(c):
    """Secondary historical corpus. It is useful for coverage but remains
    PIT-unverified until provenance replay proves when each row was observable."""
    total = 0
    warnings = []
    for season_year in SEASONS:
        suffix = f"{season_year}{str(season_year + 1)[-2:]}"
        schedule_path = f"games_{suffix}.csv"
        summary_path = f"games_summary_{suffix}.csv"
        try:
            schedule_raw, retrieved, _ = get(BLEAGUE_RAW.format(path=schedule_path))
            summary_raw, _, _ = get(BLEAGUE_RAW.format(path=summary_path))
            schedule = list(csv.DictReader(io.StringIO(schedule_raw)))
            summary = list(csv.DictReader(io.StringIO(summary_raw)))
            teams_raw, _, _ = get(BLEAGUE_RAW.format(path='teams.csv'))
            team_rows = list(csv.DictReader(io.StringIO(teams_raw)))
            season_label = str(schedule[0].get('Season') if schedule else '')
            team_name = {str(r.get('TeamId')): clean(r.get('NameShort') or r.get('NameLong') or r.get('TeamId')) for r in team_rows if str(r.get('Season') or '') == season_label}
        except Exception as e:
            warnings.append({"season": suffix, "error": repr(e)})
            continue
        teams = {}
        for row in summary:
            teams.setdefault(str(row.get("ScheduleKey")), []).append(row)
        for row in schedule:
            key = str(row.get("ScheduleKey") or "")
            rs = teams.get(key, [])
            if len(rs) < 2:
                continue
            try:
                date = iso(row.get("Date"))
                home_id = str(row.get("HomeTeamId"))
                away_id = str(row.get("AwayTeamId"))
                home = next((r for r in rs if str(r.get("TeamId")) == home_id), rs[0])
                away = next((r for r in rs if str(r.get("TeamId")) == away_id), rs[1])
                names = {home_id: team_name.get(home_id, home_id), away_id: team_name.get(away_id, away_id)}
                eid = sid(SPORT, "bleaguer", key)
                eid = upsert_event(c, SPORT, f"B.LEAGUE {home_id} vs {away_id}", date, "bleaguer-github", BLEAGUE_RAW.format(path=schedule_path), "COMPLETED", competition="B.LEAGUE", season=str(row.get("Season") or suffix))
                p1 = upsert_participant(c, SPORT, names[home_id], "team")
                p2 = upsert_participant(c, SPORT, names[away_id], "team")
                upsert_ep(c, eid, p1, p1, "A", "match", "bleaguer-github", BLEAGUE_RAW.format(path=schedule_path))
                upsert_ep(c, eid, p2, p2, "B", "match", "bleaguer-github", BLEAGUE_RAW.format(path=schedule_path))
                try:
                    sa, sb = float(home.get("PTS")), float(away.get("PTS"))
                except Exception:
                    continue
                c.execute("""INSERT OR REPLACE INTO event_outcome
                    (event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,outcome_status,source,source_url,observed_at_utc,quality_status,reason)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (eid, SPORT, p1, p2, "A" if sa > sb else "B" if sb > sa else "DRAW", sa, sb,
                     "VERIFIED", "bleaguer-github", BLEAGUE_RAW.format(path=summary_path), retrieved,
                     "PIT_REQUIRES_REPLAY", "Secondary historical corpus; publication timing is not assumed."))
                for side, pid, sr in (("A", p1, home), ("B", p2, away)):
                    for source_col, stat_name in (
                        ("PTS", "points"), ("TR", "rebounds"), ("AS", "assists"),
                        ("ST", "steals"), ("BS", "blocks"), ("TO", "turnovers"),
                        ("F2GM", "fieldGoalMade"), ("F2GA", "fieldGoalAttempted"),
                        ("F3GM", "threePointMade"), ("F3GA", "threePointAttempted"),
                        ("FTM", "freeThrowMade"), ("FTA", "freeThrowAttempted"),
                    ):
                        try:
                            value = float(sr.get(source_col))
                        except Exception:
                            continue
                        add_stat(c, eid, pid, pid, SPORT, stat_name, value, str(value),
                                 "bleaguer-github", BLEAGUE_RAW.format(path=summary_path))
                total += 1
            except Exception:
                continue
        add_snapshot(c, SPORT, "bleaguer-github", BLEAGUE_RAW.format(path=schedule_path),
                     retrieved, None, hashlib.sha256(schedule_raw.encode()).hexdigest(), "UNVERIFIABLE")
        add_snapshot(c, SPORT, "bleaguer-github", BLEAGUE_RAW.format(path=summary_path),
                     retrieved, None, hashlib.sha256(summary_raw.encode()).hexdigest(), "UNVERIFIABLE")
        c.commit()
    return total, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--official-only", action="store_true")
    ap.add_argument("--historical", action="store_true")
    a = ap.parse_args()
    c = connect()
    report = {"version": "v4.6-basketball-scope-correct", "official": 0, "historical": 0, "warnings": []}
    try:
        report["official"] = collect_official(c, SEASONS[-2:])
        if a.historical or not a.official_only:
            report["historical"], report["warnings"] = collect_historical_bleaguer(c)
        c.commit()
    finally:
        c.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
