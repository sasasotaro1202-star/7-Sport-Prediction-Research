from __future__ import annotations

"""Bounded match-data enrichment for future/current event pages.

This module only expands the persisted evidence surface. It does not modify
production probabilities or model artifacts. A page observed before the
selected prediction cutoff is marked EXACT using that observation time;
historical pages observed after the cutoff remain UNVERIFIABLE.
"""

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.seven_sport_production import add_snapshot, connect, sid, clean


ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
ACTIVE_SPORTS = ("valorant", "basketball", "volleyball", "ufc", "rizin")
PARSER_VERSION = "match-data-expansion-v2"
DETAIL_SOURCE_BY_SPORT = {
    "basketball": "bleague-game-detail",
    "valorant": "vlr-match-detail",
    "volleyball": "volleyballworld-event-detail",
    "rizin": "rizin-event-detail",
    "ufc": "ufcstats-event-detail",
}


def _dt(value):
    if not value:
        return None
    try:
        x = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _now():
    return datetime.now(timezone.utc)


def _http_get(url: str, timeout: float = 30.0):
    r = requests.get(
        url,
        headers={
            "User-Agent": "SevenSportResearchEngine/MatchDataExpansion-v1",
            "Accept-Language": "ja,en;q=0.8",
        },
        timeout=(10.0, timeout),
    )
    r.raise_for_status()
    return r.text, _now(), dict(r.headers)


def parse_jsonld(html: str):
    out = []
    soup = BeautifulSoup(html, "lxml")
    for node in soup.select("script[type='application/ld+json']"):
        try:
            payload = json.loads(node.string or node.get_text())
        except Exception:
            continue
        if isinstance(payload, list):
            out.extend(x for x in payload if isinstance(x, dict))
        elif isinstance(payload, dict):
            out.append(payload)
    return out


def _jsonld_entity(value):
    if isinstance(value, list):
        return next((x for x in value if isinstance(x, dict)), value[0] if value else None)
    return value if isinstance(value, dict) else None


def parse_jsonld_event(html: str):
    for item in parse_jsonld(html):
        typ = item.get("@type")
        types = typ if isinstance(typ, list) else [typ]
        if not any(str(x) in {"SportsEvent", "Event"} for x in types):
            continue
        location = _jsonld_entity(item.get("location"))
        organizer = _jsonld_entity(item.get("organizer"))
        venue = None
        city = region = country = address = None
        if isinstance(location, dict):
            venue = location.get("name")
            raw_address = location.get("address")
            if isinstance(raw_address, dict):
                address = raw_address.get("streetAddress")
                city = raw_address.get("addressLocality")
                region = raw_address.get("addressRegion")
                country = raw_address.get("addressCountry")
            elif isinstance(raw_address, str):
                address = raw_address
        out = {
            "name": clean(item.get("name")),
            "start_date": item.get("startDate"),
            "end_date": item.get("endDate"),
            "event_status": clean(item.get("eventStatus")),
            "venue_name": clean(venue),
            "venue_address": clean(address),
            "venue_city": clean(city),
            "venue_region": clean(region),
            "venue_country": clean(country),
            "organizer": clean(organizer.get("name") if isinstance(organizer, dict) else None),
            "description": clean(item.get("description")),
        }
        teams = []
        home_team = item.get("homeTeam")
        away_team = item.get("awayTeam")
        val = item.get("competitor")
        values = val if isinstance(val, list) else [val] if isinstance(val, dict) else []
        for team in values:
            if isinstance(team, dict) and team.get("name"):
                teams.append(clean(team["name"]))
            elif isinstance(team, str):
                teams.append(clean(team))
        out["home_team"] = clean(home_team.get("name") if isinstance(home_team, dict) else home_team)
        out["away_team"] = clean(away_team.get("name") if isinstance(away_team, dict) else away_team)
        out["teams"] = [x for x in (out["home_team"], out["away_team"]) if x] or teams[:2]
        return out
    return {}


def _numeric_line(value: str):
    s = clean(value).replace(",", "")
    return bool(re.fullmatch(r"[-+]?(?:\d+(?:\.\d+)?|\d*\.\d+)(?:%|[点本])?", s))


def _number(value: str):
    s = clean(value).replace(",", "")
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _nearest_pair(lines, index):
    before = after = None
    for j in range(index - 1, max(-1, index - 5), -1):
        if _numeric_line(lines[j]):
            before = _number(lines[j])
            break
    for j in range(index + 1, min(len(lines), index + 5)):
        if _numeric_line(lines[j]):
            after = _number(lines[j])
            break
    return before, after


def parse_bleague_detail(html: str):
    soup = BeautifulSoup(html, "lxml")
    text_lines = [clean(x) for x in soup.get_text("\n").splitlines() if clean(x)]
    text = " ".join(text_lines)
    result = {
        "teams": [
            clean(x.get_text(" ", strip=True))
            for x in soup.select(".Match_name p")
            if clean(x.get_text(" ", strip=True))
        ][:2],
        "venue_name": None,
        "tipoff": None,
        "competition": None,
        "home_away": {},
        "team_records": [],
        "standings": [],
        "season_metrics": {},
        "broadcasts": [],
    }

    m = re.search(r"会場：([^\n]+)", "\n".join(text_lines))
    if m:
        result["venue_name"] = clean(m.group(1)).split("チケット購入", 1)[0]

    m = re.search(r"(\d{1,2}:\d{2})\s*TIP\s*OFF", text, re.I)
    if m:
        result["tipoff"] = m.group(1)

    m = re.search(r"(B\.(?:PREMIER|ONE|NEXT))", text, re.I)
    if m:
        result["competition"] = "B." + m.group(1).split(".", 1)[1].upper()

    records = []
    for line in text_lines:
        m = re.fullmatch(r"(\d+)勝-(\d+)敗", line)
        if m:
            records.append((int(m.group(1)), int(m.group(2))))
    result["team_records"] = records[:2]

    rank_matches = re.findall(
        r"B\.(?:PREMIER|ONE|NEXT)｜[^\s|]+\s*(\d+|-)位",
        text,
        re.I,
    )
    result["standings"] = [
        None if x == "-" else int(x)
        for x in rank_matches[:2]
    ]

    metric_map = {
        "PPG": re.compile(r"PPG平均得点数"),
        "FG_PCT": re.compile(r"FG%フィールドゴール成功率"),
        "3FG_PCT": re.compile(r"3Fg%3Pシュート成功率"),
        "FT_PCT": re.compile(r"ft%フリースロー成功率", re.I),
        "RPG": re.compile(r"RPG平均トータルリバウンド数"),
        "APG": re.compile(r"APG平均アシスト数"),
        "BPG": re.compile(r"BPG平均ブロックショット数"),
        "SPG": re.compile(r"SPG平均スティール数"),
    }
    season_start = next(
        (i for i, line in enumerate(text_lines) if "シーズン成績" in line),
        0,
    )
    season_lines = text_lines[season_start:]
    for key, pattern in metric_map.items():
        idx = next((i for i, line in enumerate(season_lines) if pattern.search(line)), None)
        if idx is None:
            continue
        a, b = _nearest_pair(season_lines, idx)
        if a is not None or b is not None:
            result["season_metrics"][key] = [a, b]

    known_broadcasts = (
        "バスケットLIVE",
        "BS10",
        "Amazon Prime Video",
        "DAZN",
        "U-NEXT",
        "千葉テレビ",
        "NHK",
        "J SPORTS",
    )
    for name in known_broadcasts:
        if name in text:
            result["broadcasts"].append(name)

    return result



def parse_page_metadata(html: str):
    soup = BeautifulSoup(html, "lxml")

    def meta(*selectors):
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                value = clean(node.get("content") or node.get_text(" ", strip=True))
                if value:
                    return value
        return None

    canonical = None
    link = soup.select_one("link[rel='canonical']")
    if link:
        canonical = clean(link.get("href"))

    h1 = soup.find("h1")
    return {
        "title": clean(soup.title.get_text(" ", strip=True) if soup.title else None),
        "description": meta("meta[property='og:description']", "meta[name='description']"),
        "og_title": meta("meta[property='og:title']"),
        "canonical_url": canonical,
        "h1": clean(h1.get_text(" ", strip=True) if h1 else None),
    }


def parse_vlr_match_detail(html: str):
    soup = BeautifulSoup(html, "lxml")
    lines = [clean(x) for x in soup.get_text("\n").splitlines() if clean(x)]
    text = " ".join(lines)

    patch = None
    m = re.search(r"\bPatch\s+([0-9]+(?:\.[0-9]+)*)\b", text, re.I)
    if m:
        patch = m.group(1)

    match_format = None
    m = re.search(r"\b(Bo1|Bo3|Bo5)\b", text, re.I)
    if m:
        match_format = m.group(1)

    event_links = []
    for a in soup.select("a[href*='/event/']"):
        name = clean(a.get_text(" ", strip=True))
        if name and name not in event_links:
            event_links.append(name)

    betting_lines = []
    start = next((i for i, line in enumerate(lines) if line.lower() == "betting"), None)
    if start is not None:
        stop_tokens = {"head-to-head", "past matches", "watch", "full match"}
        for line in lines[start + 1:]:
            if line.lower() in stop_tokens:
                break
            if "pre-match" in line.lower() or re.search(r"\b\d+\.\d{2}\s+vs\s+\d+\.\d{2}\b", line):
                betting_lines.append(line)

    odds = []
    for line in betting_lines:
        for a, b in re.findall(r"\b(\d+\.\d{2})\s+vs\s+(\d+\.\d{2})\b", line):
            odds.extend([float(a), float(b)])

    return {
        "patch": patch,
        "format": match_format,
        "event_links": event_links[:4],
        "pre_match_betting_text": betting_lines[:4],
        "pre_match_odds": odds[:8],
        "has_pre_match_betting": bool(betting_lines),
    }


def _write_page_metadata(con, event, html, retrieved, source, exact):
    data = parse_page_metadata(html)
    values = {
        "match.page_title": data.get("title"),
        "match.page_description": data.get("description"),
        "match.page_og_title": data.get("og_title"),
        "match.page_canonical_url": data.get("canonical_url"),
        "match.page_h1": data.get("h1"),
    }
    written = 0
    for stat_name, text_value in values.items():
        if not text_value:
            continue
        _insert_stat(
            con,
            event["event_id"],
            None,
            None,
            event["sport"],
            stat_name,
            None,
            text_value,
            source,
            event["source_url"],
            retrieved.isoformat(),
            retrieved.isoformat() if exact else None,
            "EXACT" if exact else "UNVERIFIABLE",
        )
        written += 1
    return written


def _write_vlr_detail(con, event, html, retrieved, exact):
    data = parse_vlr_match_detail(html)
    values = {
        "match.vlr.patch": (None, data.get("patch")),
        "match.vlr.format": (None, data.get("format")),
        "match.vlr.has_pre_match_betting": (
            1.0 if data.get("has_pre_match_betting") else 0.0,
            None,
        ),
    }
    for idx, name in enumerate(data.get("event_links") or [], 1):
        values[f"match.vlr.event_link.{idx}"] = (None, name)
    for idx, line in enumerate(data.get("pre_match_betting_text") or [], 1):
        values[f"match.vlr.pre_match_betting.{idx}"] = (None, line)
    for idx, odd in enumerate(data.get("pre_match_odds") or [], 1):
        values[f"match.vlr.pre_match_odds.{idx}"] = (float(odd), None)

    written = 0
    for stat_name, (num, text_value) in values.items():
        if num is None and not text_value:
            continue
        _insert_stat(
            con,
            event["event_id"],
            None,
            None,
            event["sport"],
            stat_name,
            num,
            text_value,
            "vlr-match-detail",
            event["source_url"],
            retrieved.isoformat(),
            retrieved.isoformat() if exact else None,
            "EXACT" if exact else "UNVERIFIABLE",
        )
        written += 1
    return written


def _exact_for_cutoff(retrieved: datetime, event_time: datetime | None, lead_minutes: int):
    if event_time is None:
        return False, None
    cutoff = event_time - timedelta(minutes=int(lead_minutes))
    if retrieved <= cutoff:
        return True, retrieved.isoformat()
    return False, None


def _insert_stat(con, event_id, participant_id, team_id, sport, name, value_num, value_text,
                 source, source_url, observed_at, effective_at, quality):
    stat_id = sid(
        PARSER_VERSION,
        event_id,
        participant_id,
        team_id,
        name,
        value_num,
        value_text,
        source_url,
        effective_at,
    )
    con.execute(
        """
        INSERT OR REPLACE INTO match_stats(
          stat_id,event_id,participant_id,team_id,sport,observed_at_utc,
          effective_at_utc,stat_name,value_num,value_text,unit,source,source_url,
          quality_status,confidence
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            stat_id,
            event_id,
            participant_id,
            team_id,
            sport,
            observed_at,
            effective_at,
            name,
            value_num,
            value_text,
            None,
            source,
            source_url,
            quality,
            1.0 if quality == "EXACT" else 0.0,
        ),
    )


def _participants(con, event_id):
    return con.execute(
        """
        SELECT ep.side, ep.participant_id, ep.team_id, p.canonical_name
          FROM event_participant ep
          LEFT JOIN participant p ON p.participant_id=ep.participant_id
         WHERE ep.event_id=? AND ep.side IN ('A','B')
         ORDER BY CASE ep.side WHEN 'A' THEN 0 ELSE 1 END
        """,
        (event_id,),
    ).fetchall()


def _cache_fresh(con, source, url, max_age_minutes=45):
    cutoff = (_now() - timedelta(minutes=max_age_minutes)).isoformat()
    return con.execute(
        """
        SELECT 1 FROM source_snapshot
         WHERE source=? AND source_url=?
           AND retrieved_at_utc >= ?
         LIMIT 1
        """,
        (source, url, cutoff),
    ).fetchone() is not None


def _write_jsonld(con, event, html, retrieved, source, exact):
    data = parse_jsonld_event(html)
    if not data:
        return 0
    values = {
        "match.venue_name": (None, data.get("venue_name")),
        "match.venue_address": (None, data.get("venue_address")),
        "match.venue_city": (None, data.get("venue_city")),
        "match.venue_region": (None, data.get("venue_region")),
        "match.venue_country": (None, data.get("venue_country")),
        "match.organizer": (None, data.get("organizer")),
        "match.event_status": (None, data.get("event_status")),
        "match.description": (None, data.get("description")),
        "match.structured_home_team": (None, data.get("home_team")),
        "match.structured_away_team": (None, data.get("away_team")),
    }
    written = 0
    for stat_name, (num, text_value) in values.items():
        if not text_value:
            continue
        _insert_stat(
            con,
            event["event_id"],
            None,
            None,
            event["sport"],
            stat_name,
            num,
            clean(text_value),
            source,
            event["source_url"],
            retrieved.isoformat(),
            retrieved.isoformat() if exact else None,
            "EXACT" if exact else "UNVERIFIABLE",
        )
        written += 1
    # Structured team roles remain event-level metadata; no implicit participant merge.

    return written


def _write_bleague(con, event, html, retrieved, exact):
    data = parse_bleague_detail(html)
    names = _participants(con, event["event_id"])
    written = 0

    scalar_values = {
        "match.venue_name": (None, data.get("venue_name")),
        "match.tipoff": (None, data.get("tipoff")),
        "match.competition": (None, data.get("competition")),
        "match.broadcast_count": (float(len(data.get("broadcasts") or [])), None),
    }
    for stat_name, (num, text_value) in scalar_values.items():
        if num is None and not text_value:
            continue
        _insert_stat(
            con, event["event_id"], None, None, event["sport"], stat_name, num,
            text_value, "bleague-game-detail", event["source_url"],
            retrieved.isoformat(),
            retrieved.isoformat() if exact else None,
            "EXACT" if exact else "UNVERIFIABLE",
        )
        written += 1

    for idx, (wins, losses) in enumerate(data.get("team_records") or []):
        if idx >= len(names):
            break
        participant_id, team_id = names[idx][1], names[idx][2]
        for key, value in (
            ("team.season_wins", float(wins)),
            ("team.season_losses", float(losses)),
        ):
            _insert_stat(
                con, event["event_id"], participant_id, team_id, event["sport"],
                key, value, None, "bleague-game-detail", event["source_url"],
                retrieved.isoformat(),
                retrieved.isoformat() if exact else None,
                "EXACT" if exact else "UNVERIFIABLE",
            )
            written += 1

    for idx, rank in enumerate(data.get("standings") or []):
        if idx >= len(names) or rank is None:
            continue
        participant_id, team_id = names[idx][1], names[idx][2]
        _insert_stat(
            con, event["event_id"], participant_id, team_id, event["sport"],
            "team.standing_rank", float(rank), None, "bleague-game-detail",
            event["source_url"], retrieved.isoformat(),
            retrieved.isoformat() if exact else None,
            "EXACT" if exact else "UNVERIFIABLE",
        )
        written += 1

    for metric, values in (data.get("season_metrics") or {}).items():
        for idx, value in enumerate(values[:2]):
            if idx >= len(names) or value is None:
                continue
            participant_id, team_id = names[idx][1], names[idx][2]
            _insert_stat(
                con, event["event_id"], participant_id, team_id, event["sport"],
                f"team.season_{metric.lower()}", value, None,
                "bleague-game-detail", event["source_url"],
                retrieved.isoformat(),
                retrieved.isoformat() if exact else None,
                "EXACT" if exact else "UNVERIFIABLE",
            )
            written += 1



    for idx, name in enumerate(data.get("broadcasts") or []):
        _insert_stat(
            con, event["event_id"], None, None, event["sport"],
            f"match.broadcast.{idx + 1}", None, name,
            "bleague-game-detail", event["source_url"],
            retrieved.isoformat(),
            retrieved.isoformat() if exact else None,
            "EXACT" if exact else "UNVERIFIABLE",
        )
        written += 1

    return written


def enrich_one(con, event, lead_minutes=60):
    url = clean(event["source_url"])
    if not url:
        return {"status": "SKIPPED_NO_URL", "event_id": event["event_id"]}
    source = DETAIL_SOURCE_BY_SPORT.get(event["sport"], f"{urlparse(url).netloc}-event-detail")
    if event["sport"] not in ACTIVE_SPORTS:
        return {"status": "SKIPPED_SCOPE", "event_id": event["event_id"]}

    try:
        event_time = _dt(event["event_time_utc"])
        retrieved = _now()
        raw, retrieved, _headers = _http_get(url)
        exact, available_at = _exact_for_cutoff(retrieved, event_time, lead_minutes)

        content_hash = hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()
        add_snapshot(
            con,
            event["sport"],
            source,
            url,
            retrieved.isoformat(),
            event["event_time_utc"],
            content_hash,
            "EXACT" if exact else "UNVERIFIABLE",
            source_available_at_utc=available_at,
            provenance={
                "sport": event["sport"],
                "parser": PARSER_VERSION,
                "evidence": "prospective_http_observation" if exact else "historical_or_late_observation",
                "prediction_lead_minutes": int(lead_minutes),
            },
        )

        page_written = _write_page_metadata(con, event, raw, retrieved, source, exact)
        detail_written = _write_jsonld(con, event, raw, retrieved, source, exact)
        if event["sport"] == "basketball" and "bleague.jp" in url:
            detail_written += _write_bleague(con, event, raw, retrieved, exact)
        if event["sport"] == "valorant" and "vlr.gg" in url:
            detail_written += _write_vlr_detail(con, event, raw, retrieved, exact)

        written = page_written + detail_written
        parser_status = "OK" if written > 0 else "NO_STRUCTURED_DATA"
        return {
            "status": "OK" if parser_status == "OK" else "PARSER_EMPTY",
            "event_id": event["event_id"],
            "source": source,
            "exact": exact,
            "available_at": available_at,
            "written_stats": written,
            "page_metadata_fields": page_written,
            "detail_fields": detail_written,
            "parser_status": parser_status,
        }
    except Exception as exc:
        return {
            "status": "FETCH_ERROR",
            "event_id": event["event_id"],
            "source": source,
            "error_type": type(exc).__name__,
            "error": repr(exc),
        }


def select_events(con, sport, horizon_days=14, max_events=40):
    now = _now()
    upper = now + timedelta(days=int(horizon_days))
    lower = now + timedelta(minutes=5)
    return con.execute(
        """
        SELECT event_id,sport,event_time_utc,event_type,status,source_url
          FROM event
         WHERE sport=?
           AND event_time_utc IS NOT NULL
           AND datetime(event_time_utc) > datetime(?)
           AND datetime(event_time_utc) <= datetime(?)
           AND UPPER(COALESCE(status,'')) NOT IN ('CANCELLED','VOID')
           AND source_url IS NOT NULL
         ORDER BY datetime(event_time_utc), event_id
         LIMIT ?
        """,
        (sport, lower.isoformat(), upper.isoformat(), int(max_events)),
    ).fetchall()


def _summarize_run_status(selected_count, processed_count, skipped_fresh, errors, parser_empty):
    if int(selected_count) == 0:
        return "NO_CANDIDATE_EVENTS"
    if int(errors) > 0 or int(parser_empty) > 0:
        return "DEGRADED"
    if int(processed_count) == 0 and int(skipped_fresh) == int(selected_count):
        return "CACHE_FRESH"
    return "OK"


def run(sport, horizon_days=14, max_events=40, lead_minutes=60):
    con = connect()
    before = con.execute(
        "SELECT COUNT(*) FROM match_stats WHERE sport=?",
        (sport,),
    ).fetchone()[0]
    selected = select_events(con, sport, horizon_days=horizon_days, max_events=max_events)
    results = []
    skipped_fresh = 0
    errors = 0
    parser_empty = 0
    exact_count = 0
    unverifiable_count = 0
    for row in selected:
        event = dict(row)
        source = DETAIL_SOURCE_BY_SPORT.get(sport, f"{urlparse(event['source_url']).netloc}-event-detail")
        event_dt = _dt(event["event_time_utc"])
        if event_dt is None:
            cache_age = 45
        else:
            minutes_to_event = max(0.0, (event_dt - _now()).total_seconds() / 60.0)
            cache_age = 5 if minutes_to_event <= 90 else 15 if minutes_to_event <= 360 else 45
        if _cache_fresh(con, source, event["source_url"], max_age_minutes=cache_age):
            skipped_fresh += 1
            continue
        result = enrich_one(con, event, lead_minutes=lead_minutes)
        results.append(result)
        if result.get("status") == "FETCH_ERROR":
            errors += 1
        if result.get("status") == "PARSER_EMPTY":
            parser_empty += 1
        if result.get("exact") is True:
            exact_count += 1
        elif result.get("exact") is False:
            unverifiable_count += 1
        con.commit()
    after = con.execute(
        "SELECT COUNT(*) FROM match_stats WHERE sport=?",
        (sport,),
    ).fetchone()[0]
    con.close()
    status = _summarize_run_status(
        len(selected), len(results), skipped_fresh, errors, parser_empty
    )
    return {
        "parser_version": PARSER_VERSION,
        "sport": sport,
        "selected_events": len(selected),
        "skipped_fresh": skipped_fresh,
        "processed_events": len(results),
        "fetch_errors": errors,
        "parser_empty": parser_empty,
        "exact_observations": exact_count,
        "unverifiable_observations": unverifiable_count,
        "new_match_stats": after - before,
        "results": results,
        "status": status,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", choices=ACTIVE_SPORTS, required=True)
    ap.add_argument("--horizon-days", type=int, default=14)
    ap.add_argument("--max-events", type=int, default=40)
    ap.add_argument("--lead-minutes", type=int, default=60)
    args = ap.parse_args()
    report = run(
        args.sport,
        horizon_days=max(1, args.horizon_days),
        max_events=max(1, args.max_events),
        lead_minutes=max(1, args.lead_minutes),
    )
    out = ROOT / "results" / "match_data_expansion"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.sport}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
