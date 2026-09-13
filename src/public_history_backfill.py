from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.storage.db_v45 import connect, utcnow
from src.seven_sport_production import (
    add_snapshot,
    add_stat,
    upsert_ep,
    upsert_event,
    upsert_participant,
)

ROOT = Path(__file__).resolve().parents[1]

VALORANT_RESULTS = (
    "https://raw.githubusercontent.com/rush2pranav/valorant-pro-scene-tracker/"
    "main/data/results.csv"
)
NBA_GAMES = "https://raw.githubusercontent.com/sportsdataverse/hoopR-data/main/nba/nba_games_in_data_repo.csv"
WNBA_GAMES = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_wnba_schedules/wnba_games_in_data_repo.csv"
FIBA_2019 = "https://raw.githubusercontent.com/gkaramanis/FIBA-Basketbal-World-Cup/master/Data/FIBA-WBC19-results.csv"
RIZIN_TAG = "https://jp.rizinff.com/_tags/%E8%A9%A6%E5%90%88%E7%B5%90%E6%9E%9C"
VOLLEYBALL_SEEDS = [
    "https://en.volleyballworld.com/volleyball/competitions",
    "https://en.volleyballworld.com/volleyball/matches",
]


def iso(value):
    if not value:
        return None
    s = str(value).strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    try:
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def http(url: str, timeout: int = 30):
    headers = {"User-Agent": "SevenSportResearchEngine/4.5.13"}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.text, utcnow(), "direct"
    except Exception:
        # Jina is used only as a read-only fallback for public pages that reject
        # GitHub-hosted runner IPs. Retrieval time is never treated as publication time.
        proxy = "https://r.jina.ai/http://" + url.replace("https://", "").replace("http://", "")
        r = requests.get(proxy, headers=headers, timeout=max(timeout, 45))
        r.raise_for_status()
        return r.text, utcnow(), "jina_reader"


def snapshot(c, sport, source, url, retrieved, event_time, text, availability="UNVERIFIABLE"):
    payload_hash = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
    add_snapshot(c, sport, source, url, retrieved, event_time, payload_hash, availability)


def outcome(c, sport, eid, p1, p2, side):
    c.execute(
        """INSERT OR REPLACE INTO event_outcome
        (event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,
         outcome_status,source,source_url,observed_at_utc,quality_status,reason)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (eid, sport, p1, p2, side, None, None, "VERIFIED", "public_historical_dataset",
         "", utcnow(), "PIT_REQUIRES_REPLAY", "Historical label source; never used as pre-event feature data."),
    )


def backfill_csv_games(c, url, sport, competition):
    raw, retrieved, via = http(url)
    rows = list(csv.DictReader(io.StringIO(raw)))
    added = 0
    for row in rows:
        keys = {str(k).lower(): v for k, v in row.items()}
        home = clean(keys.get("home_team_name") or keys.get("home_team") or keys.get("home") or keys.get("home_team_abbrev"))
        away = clean(keys.get("away_team_name") or keys.get("away_team") or keys.get("away") or keys.get("away_team_abbrev") or keys.get("visitor_team_name"))
        if not home or not away:
            continue
        date = keys.get("game_date") or keys.get("date") or keys.get("start_date") or keys.get("start_time")
        et = iso(date)
        name = f"{home} vs {away}"
        eid = upsert_event(c, sport, name, et, "public-dataset", url, "COMPLETED", competition=competition, season=str(date)[:4] if date else None)
        p1 = upsert_participant(c, sport, home, "team")
        p2 = upsert_participant(c, sport, away, "team")
        upsert_ep(c, eid, p1, p1, "A", "match", "public-dataset", url)
        upsert_ep(c, eid, p2, p2, "B", "match", "public-dataset", url)
        hs = keys.get("home_score") or keys.get("home_team_score") or keys.get("home_score_final")
        as_ = keys.get("away_score") or keys.get("visitor_team_score") or keys.get("away_score_final")
        try:
            hscore, ascore = float(hs), float(as_)
        except Exception:
            hscore = ascore = None
        if hscore is not None and ascore is not None:
            side = "A" if hscore > ascore else "B" if ascore > hscore else "DRAW"
            outcome(c, sport, eid, p1, p2, side)
            add_stat(c, eid, p1, p1, sport, "score.final", hscore, str(hscore), "public-dataset", url)
            add_stat(c, eid, p2, p2, sport, "score.final", ascore, str(ascore), "public-dataset", url)
        added += 1
    snapshot(c, sport, "public-dataset", url, retrieved, None, raw, "UNVERIFIABLE")
    return added


def backfill_valorant(c):
    raw, retrieved, _ = http(VALORANT_RESULTS)
    rows = list(csv.DictReader(io.StringIO(raw)))
    added = 0
    for row in rows:
        team1 = clean(row.get("team1"))
        team2 = clean(row.get("team2"))
        if not team1 or not team2:
            continue
        et = iso(row.get("time_completed") or row.get("date"))
        tournament = clean(row.get("tournament_name"))
        stage = clean(row.get("round_info"))
        eid = upsert_event(c, "valorant", f"{team1} vs {team2}", et, "public-vlr-dataset", VALORANT_RESULTS,
                           "COMPLETED", competition=tournament or None, stage=stage or None,
                           season=str(et)[:4] if et else None)
        p1 = upsert_participant(c, "valorant", team1, "team")
        p2 = upsert_participant(c, "valorant", team2, "team")
        upsert_ep(c, eid, p1, p1, "A", "match", "public-vlr-dataset", VALORANT_RESULTS)
        upsert_ep(c, eid, p2, p2, "B", "match", "public-vlr-dataset", VALORANT_RESULTS)
        try:
            s1, s2 = float(row.get("score1")), float(row.get("score2"))
        except Exception:
            s1 = s2 = None
        if s1 is not None and s2 is not None:
            side = "A" if s1 > s2 else "B" if s2 > s1 else "DRAW"
            outcome(c, "valorant", eid, p1, p2, side)
            add_stat(c, eid, p1, p1, "valorant", "series.score", s1, str(s1), "public-vlr-dataset", VALORANT_RESULTS)
            add_stat(c, eid, p2, p2, "valorant", "series.score", s2, str(s2), "public-vlr-dataset", VALORANT_RESULTS)
        added += 1
    snapshot(c, "valorant", "public-vlr-dataset", VALORANT_RESULTS, retrieved, None, raw, "UNVERIFIABLE")
    return added


def backfill_rizin(c, max_pages=100):
    index, retrieved, via = http(RIZIN_TAG)
    urls = sorted(set(re.findall(r"https://jp\.rizinff\.com/_ct/\d+", index)))
    if not urls:
        urls = sorted(set(urljoin(RIZIN_TAG, x) for x in re.findall(r"/_ct/\d+", index)))
    urls = urls[:max_pages]
    added = 0
    for url in urls:
        try:
            text, rr, route = http(url)
        except Exception:
            continue
        title_match = re.search(r"(?:#\s*)?([^\n]{4,120})試合結果一覧", text)
        title = clean(title_match.group(1) if title_match else url)
        date_match = re.search(r"(20\d{2})[-年./](\d{1,2})[-月./](\d{1,2})", text)
        et = iso("-".join(date_match.groups())) if date_match else None
        # Official result pages expose WIN/LOSE pairs in plain text/HTML.
        pairs = re.findall(r"\(WIN\)\s*([^<\n]+?)\s+vs\.?\s+([^<\n]+?)\s*\(LOSE\)", text, re.I)
        if not pairs:
            pairs = re.findall(r"\(LOSE\)\s*([^<\n]+?)\s+vs\.?\s+([^<\n]+?)\s*\(WIN\)", text, re.I)
        for a, b in pairs:
            a, b = clean(a), clean(b)
            if not a or not b or len(a) > 80 or len(b) > 80:
                continue
            eid = upsert_event(c, "rizin", f"{a} vs {b}", et, "jp.rizinff.com", url, "COMPLETED",
                               competition=title, season=str(et)[:4] if et else None)
            p1 = upsert_participant(c, "rizin", a, "fighter")
            p2 = upsert_participant(c, "rizin", b, "fighter")
            upsert_ep(c, eid, p1, p1, "A", "fight", "jp.rizinff.com", url)
            upsert_ep(c, eid, p2, p2, "B", "fight", "jp.rizinff.com", url)
            side = "A" if "(WIN)" in text[text.find(a):text.find(a)+200] else "B"
            outcome(c, "rizin", eid, p1, p2, side)
            added += 1
        if added:
            snapshot(c, "rizin", "jp.rizinff.com", url, rr, et, text, "UNVERIFIABLE")
    return added


def backfill_volleyball(c, max_pages=80):
    queue = list(VOLLEYBALL_SEEDS)
    seen = set()
    added = 0
    while queue and len(seen) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            text, retrieved, via = http(url)
        except Exception:
            continue
        # Volleyball World pages are JS-heavy; Jina fallback exposes canonical links.
        links = set(re.findall(r"https://en\.volleyballworld\.com/volleyball/[^\s)\"<>]+", text))
        for link in links:
            if re.search(r"/matches?/|/competitions/", link, re.I) and link not in seen:
                queue.append(link)
        for m in re.finditer(r"([A-Z][^\n]{2,70})\s+[-–]\s+([A-Z][^\n]{2,70})", text):
            a, b = clean(m.group(1)), clean(m.group(2))
            if len(a) > 70 or len(b) > 70:
                continue
            date_match = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text[max(0, m.start()-500):m.end()+500])
            et = iso("-".join(date_match.groups())) if date_match else None
            if not et:
                continue
            eid = upsert_event(c, "volleyball", f"{a} vs {b}", et, "volleyballworld.com", url, "COMPLETED")
            p1 = upsert_participant(c, "volleyball", a, "team")
            p2 = upsert_participant(c, "volleyball", b, "team")
            upsert_ep(c, eid, p1, p1, "A", "match", "volleyballworld.com", url)
            upsert_ep(c, eid, p2, p2, "B", "match", "volleyballworld.com", url)
            added += 1
        snapshot(c, "volleyball", "volleyballworld.com", url, retrieved, None, text, "UNVERIFIABLE")
    return added


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--sports", default="valorant,basketball,volleyball,rizin")
    a = p.parse_args()
    c = connect()
    out = {}
    errors = []
    try:
        for sport in [x.strip() for x in a.sports.split(",") if x.strip()]:
            try:
                if sport == "valorant":
                    out[sport] = backfill_valorant(c)
                elif sport == "basketball":
                    out[sport] = backfill_csv_games(c, NBA_GAMES, "basketball", "NBA")
                    out["wnba"] = backfill_csv_games(c, WNBA_GAMES, "basketball", "WNBA")
                    # One explicit international benchmark dataset is added as a
                    # separate competition layer; it is label-only until PIT replay.
                    try:
                        out["fiba_world_cup_2019"] = backfill_csv_games(c, FIBA_2019, "basketball", "FIBA World Cup 2019")
                    except Exception as e:
                        errors.append({"sport": "basketball:fiba", "error": repr(e)})
                elif sport == "rizin":
                    out[sport] = backfill_rizin(c)
                elif sport == "volleyball":
                    out[sport] = backfill_volleyball(c)
            except Exception as e:
                errors.append({"sport": sport, "error": repr(e)})
        c.commit()
    finally:
        c.close()
    report = {"parser_version": "v4.5.13-public-history", "added": out, "errors": errors, "timestamp_utc": utcnow()}
    pth = ROOT / "results" / "public_history_backfill.json"
    pth.parent.mkdir(parents=True, exist_ok=True)
    pth.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
