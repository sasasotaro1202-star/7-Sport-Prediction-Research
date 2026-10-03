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
# Official legacy schedule rendering is retained as a read-only current-schedule
# fallback when the current page serves no parseable match anchors to requests.
BLEAGUE_SCHEDULE_FALLBACK = "https://www.bleague.jp/schedule_old2208/"
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


def get(url, timeout=45):
    # Network/transient failures must not silently erase an otherwise valid
    # historical partition. Retry boundedly with exponential backoff while
    # preserving the retrieval timestamp as the provenance observation.
    import time
    last = None
    for attempt in range(5):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"},
                timeout=(min(15, int(timeout)), int(timeout)),
            )
            status = int(r.status_code)
            if status == 429 or 500 <= status < 600:
                raise requests.HTTPError(f"transient_http_status={status}", response=r)
            r.raise_for_status()
            return r.text, utcnow(), r.headers
        except (
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        ) as exc:
            last = exc
        except requests.HTTPError as exc:
            last = exc
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if status != 429 and not (isinstance(status, int) and 500 <= status < 600):
                raise
        if attempt < 4:
            time.sleep(min(8.0, 1.0 * (2 ** attempt)))
    raise last


JP_PREFECTURES = (
    "北海道","青森県","岩手県","宮城県","秋田県","山形県","福島県",
    "茨城県","栃木県","群馬県","埼玉県","千葉県","東京都","神奈川県",
    "新潟県","富山県","石川県","福井県","山梨県","長野県","岐阜県",
    "静岡県","愛知県","三重県","滋賀県","京都府","大阪府","兵庫県",
    "奈良県","和歌山県","鳥取県","島根県","岡山県","広島県","山口県",
    "徳島県","香川県","愛媛県","高知県","福岡県","佐賀県","長崎県",
    "熊本県","大分県","宮崎県","鹿児島県","沖縄県",
)
DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[/.](\d{1,2})(?:\s*[\(（][^\)）]*[\)）])?")
TIME_RE = re.compile(r"(?<!\d)(\d{1,2}:\d{2})(?!\d)")
TIER_RE = re.compile(r"\bB\.(PREMIER|ONE|NEXT)\b", re.I)


def _game_id(href):
    m = re.search(r"ScheduleKey=(\d+)", href or "")
    return m.group(1) if m else None


def _normalise_href(href):
    href = str(href or "").strip()
    if href.startswith("/"):
        return "https://www.bleague.jp" + href
    return href


def _fallback_container(anchor):
    for parent in anchor.parents:
        links = parent.select("a[href*='game_detail']")
        text_value = clean(parent.get_text(" ", strip=True))
        if len(links) == 1 and TIME_RE.search(text_value) and len(text_value) <= 700:
            return parent
    return anchor.parent or anchor


def _fallback_date(anchor, container):
    for node in (container, *list(container.parents)[:5]):
        text_value = clean(node.get_text(" ", strip=True))
        m = DATE_RE.search(text_value)
        if m:
            return m
    for node in anchor.find_all_previous(["h2", "h3", "h4", "time", "dt"], limit=24):
        text_value = clean(node.get_text(" ", strip=True))
        m = DATE_RE.search(text_value)
        if m:
            return m
    return None


def _strip_venue_tail(text_value):
    value = clean(text_value)
    value = DATE_RE.sub(" ", value)
    value = TIME_RE.sub(" ", value)
    value = TIER_RE.sub(" ", value)
    for pref in JP_PREFECTURES:
        marker = value.find(pref)
        if marker >= 0:
            value = value[:marker]
            break
    return clean(value.strip(" |｜"))


def _fallback_names(text_value):
    text_value = clean(text_value)
    compact = TIME_RE.sub(" ", DATE_RE.sub(" ", TIER_RE.sub(" ", text_value)))
    before_pipe = clean(compact.split("|", 1)[0].split("｜", 1)[0])

    for sep in (" VS ", " vs ", "VS", "vs"):
        if sep in before_pipe:
            left, right = before_pipe.split(sep, 1)
            left = _strip_venue_tail(left)
            right = _strip_venue_tail(right)
            left_tokens = [clean(x) for x in left.split() if clean(x)]
            right_tokens = [clean(x) for x in right.split() if clean(x)]
            if left_tokens and right_tokens:
                return [left_tokens[0], right_tokens[0]]

    left = _strip_venue_tail(before_pipe)
    tokens = [clean(x) for x in left.split() if clean(x)]
    return tokens[:2] if len(tokens) >= 2 else []


def _fallback_competition(text_value):
    m = TIER_RE.search(text_value or "")
    if m:
        return "B." + m.group(1).upper()
    return "B.LEAGUE"


def _upsert_official_match(
    c,
    href,
    names,
    event_time,
    retrieved,
    competition,
    season_year,
    scores=None,
):
    game_id = _game_id(href)
    if not game_id or len(names) < 2 or not event_time:
        return None
    eid = sid(SPORT, "bleague-official", game_id)
    status = "COMPLETED" if scores else "SCHEDULED"
    eid = upsert_event(
        c,
        SPORT,
        f"{names[0]} vs {names[1]}",
        event_time,
        "bleague-official",
        href,
        status,
        competition=competition or "B.LEAGUE",
        season=f"{season_year}-{str(season_year + 1)[-2:]}",
    )
    p1 = upsert_participant(c, SPORT, names[0], "team")
    p2 = upsert_participant(c, SPORT, names[1], "team")
    upsert_ep(c, eid, p1, p1, "A", "match", "bleague-official", href)
    upsert_ep(c, eid, p2, p2, "B", "match", "bleague-official", href)
    if scores:
        sa, sb = scores[0]
        c.execute(
            """INSERT OR REPLACE INTO event_outcome
               (event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,outcome_status,source,source_url,observed_at_utc,quality_status,reason)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                eid, SPORT, p1, p2,
                "A" if sa > sb else "B" if sb > sa else "DRAW",
                sa, sb, "VERIFIED", "bleague-official", href, retrieved,
                "PIT_REQUIRES_REPLAY",
                "Official B.LEAGUE schedule/result page.",
            ),
        )
    return eid


def parse_schedule_page(c, html, retrieved, url, season_year, month):
    soup = BeautifulSoup(html, "lxml")
    added = 0
    seen_game_ids = set()
    for li in soup.select("li.MatchList"):

        a = li.select_one("a[href*='game_detail']")
        if not a:
            continue
        href = a.get("href", "")
        if href.startswith("/"):
            href = "https://www.bleague.jp" + href
        game_id = re.search(r"ScheduleKey=(\d+)", href)
        game_id = game_id.group(1) if game_id else None
        if not game_id or game_id in seen_game_ids:
            continue
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
        seen_game_ids.add(game_id)
        added += 1

    # Current markup has changed over time. Parse rendered game-detail anchors
    # as a bounded fallback while preserving exact ScheduleKey identity and the
    # existing strict PIT status.
    for a in soup.select("a[href*='game_detail']"):
        href = _normalise_href(a.get("href", ""))
        game_id = _game_id(href)
        if not game_id or game_id in seen_game_ids:
            continue
        container = _fallback_container(a)
        text_value = clean(container.get_text(" ", strip=True))
        tm = TIME_RE.search(text_value)
        md = _fallback_date(a, container)
        if not tm or not md:
            continue
        y = season_year if int(md.group(1)) >= 9 else season_year + 1
        et = iso(f"{y:04d}-{int(md.group(1)):02d}-{int(md.group(2)):02d}T{tm.group(1)}:00")
        names = _fallback_names(clean(a.get_text(" ", strip=True)) or text_value)
        if len(names) < 2:
            names = _fallback_names(text_value)
        competition = _fallback_competition(text_value)
        if _upsert_official_match(c, href, names, et, retrieved, competition, season_year):
            seen_game_ids.add(game_id)
            added += 1

    add_snapshot(c, SPORT, "bleague-official", url, retrieved, None,
                 hashlib.sha256(html.encode("utf-8", "ignore")).hexdigest(), "UNVERIFIABLE")
    return added


def collect_official(c, season_years):
    total = 0
    errors = []
    requests_attempted = 0
    empty_pages = 0
    for season_year in season_years:
        season_added = 0
        for month in range(1, 13):
            url = BLEAGUE_SCHEDULE.format(month=month, season_year=season_year)
            requests_attempted += 1
            try:
                html, retrieved, _ = get(url)
                added = parse_schedule_page(c, html, retrieved, url, season_year, month)
                total += added
                season_added += added
                if added == 0:
                    empty_pages += 1
            except Exception as exc:
                errors.append({
                    "season_year": int(season_year),
                    "month": int(month),
                    "url": url,
                    "error_type": type(exc).__name__,
                    "error": repr(exc),
                })
        # The current schedule endpoint can return a successful HTML shell with
        # no rendered game anchors to non-browser clients. In that case, use the
        # official legacy schedule rendering once for the season. It is still
        # parsed with the same exact ScheduleKey/timestamp/name rules.
        current_season_year = (
            datetime.now(timezone.utc).year
            if datetime.now(timezone.utc).month >= 9
            else datetime.now(timezone.utc).year - 1
        )
        if season_added == 0 and season_year == current_season_year:
            fallback_url = BLEAGUE_SCHEDULE_FALLBACK
            requests_attempted += 1
            try:
                html, retrieved, _ = get(fallback_url)
                fallback_added = parse_schedule_page(
                    c, html, retrieved, fallback_url, season_year, 0
                )
                total += fallback_added
            except Exception as exc:
                errors.append({
                    "season_year": int(season_year),
                    "month": None,
                    "url": fallback_url,
                    "error_type": type(exc).__name__,
                    "error": repr(exc),
                })
        c.commit()
    return total, errors, requests_attempted, empty_pages


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
                                 "bleaguer-github", BLEAGUE_RAW.format(path=summary_path), effective_at_utc=date)
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
    report = {
        "version": "v4.6-basketball-scope-correct",
        "official": 0,
        "official_requests": 0,
        "official_empty_pages": 0,
        "official_errors": [],
        "historical": 0,
        "warnings": [],
    }
    try:
        (
            report["official"],
            report["official_errors"],
            report["official_requests"],
            report["official_empty_pages"],
        ) = collect_official(c, SEASONS[-2:])
        report["official_status"] = (
            "ERROR" if report["official_errors"] and report["official"] == 0
            else "PARTIAL_SOURCE_ERROR" if report["official_errors"]
            else "PARSER_ZERO" if report["official"] == 0 and report["official_empty_pages"] == report["official_requests"]
            else "OK"
        )
        if a.historical or not a.official_only:
            report["historical"], report["warnings"] = collect_historical_bleaguer(c)
        c.commit()
    finally:
        c.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
