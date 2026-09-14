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

from src.storage.db_v45 import connect, utcnow
from src.seven_sport_production import (
    add_snapshot,
    add_stat,
    upsert_ep,
    upsert_event,
    upsert_participant,
)

ROOT = Path(__file__).resolve().parents[1]

VALORANT_RESULTS = "https://raw.githubusercontent.com/rush2pranav/valorant-pro-scene-tracker/main/data/results.csv"
NBA_GAMES = "https://raw.githubusercontent.com/sportsdataverse/hoopR-data/main/nba/nba_games_in_data_repo.csv"
WNBA_GAMES = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_wnba_schedules/wnba_games_in_data_repo.csv"
FIBA_2019 = "https://raw.githubusercontent.com/gkaramanis/FIBA-Basketbal-World-Cup/master/data/FIBA-WBC19-results.csv"
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


def first_value(keys, *names):
    for name in names:
        value = keys.get(name)
        if value is not None and clean(value):
            return clean(value)
    return ""


def http(url: str, timeout: int = 30):
    headers = {"User-Agent": "SevenSportResearchEngine/4.5.15"}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.text, utcnow(), "direct"
    except Exception:
        proxy = "https://r.jina.ai/http://" + url.replace("https://", "").replace("http://", "")
        r = requests.get(proxy, headers=headers, timeout=max(timeout, 45))
        r.raise_for_status()
        return r.text, utcnow(), "jina_reader"


def snapshot(c, sport, source, url, retrieved, event_time, text, availability="UNVERIFIABLE"):
    payload_hash = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
    add_snapshot(c, sport, source, url, retrieved, event_time, payload_hash, availability)


def outcome(c, sport, eid, p1, p2, side, source_url):
    c.execute(
        """INSERT OR REPLACE INTO event_outcome
        (event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,
         outcome_status,source,source_url,observed_at_utc,quality_status,reason)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (eid, sport, p1, p2, side, None, None, "VERIFIED", "public_historical_dataset",
         source_url, utcnow(), "PIT_REQUIRES_REPLAY",
         "Historical label source; never used as pre-event feature data."),
    )


def backfill_csv_games(c, url, sport, competition):
    raw, retrieved, _ = http(url)
    rows = list(csv.DictReader(io.StringIO(raw)))
    added = 0
    for row in rows:
        keys = {str(k).strip().lower(): v for k, v in row.items()}
        # hoopR has changed/expanded its flattened schedule schema over time.
        # Accept stable semantic aliases rather than one brittle column spelling.
        home = first_value(
            keys,
            "home_team_name", "home_team_display_name", "home_display_name",
            "home_team", "home", "home_team_abbrev", "home_abbreviation",
        )
        away = first_value(
            keys,
            "away_team_name", "away_team_display_name", "away_display_name",
            "away_team", "away", "away_team_abbrev", "away_abbreviation",
            "visitor_team_name", "visitor_team", "visitor",
        )
        if not home or not away or home == away:
            continue
        date = first_value(keys, "game_date", "date", "start_date", "start_time", "game_datetime", "game_et")
        et = iso(date)
        eid = upsert_event(
            c, sport, f"{home} vs {away}", et, "public-dataset", url,
            "COMPLETED", competition=competition, season=str(date)[:4] if date else None,
        )
        p1 = upsert_participant(c, sport, home, "team")
        p2 = upsert_participant(c, sport, away, "team")
        upsert_ep(c, eid, p1, p1, "A", "match", "public-dataset", url)
        upsert_ep(c, eid, p2, p2, "B", "match", "public-dataset", url)
        hs = first_value(keys, "home_score", "home_team_score", "home_score_final", "home_points", "home_team_points")
        as_ = first_value(keys, "away_score", "away_team_score", "away_score_final", "away_points", "away_team_points", "visitor_score")
        try:
            hscore, ascore = float(hs), float(as_)
        except Exception:
            hscore = ascore = None
        if hscore is not None and ascore is not None:
            side = "A" if hscore > ascore else "B" if ascore > hscore else "DRAW"
            outcome(c, sport, eid, p1, p2, side, url)
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
            outcome(c, "valorant", eid, p1, p2, side, VALORANT_RESULTS)
            add_stat(c, eid, p1, p1, "valorant", "series.score", s1, str(s1), "public-vlr-dataset", VALORANT_RESULTS)
            add_stat(c, eid, p2, p2, "valorant", "series.score", s2, str(s2), "public-vlr-dataset", VALORANT_RESULTS)
        added += 1
    snapshot(c, "valorant", "public-vlr-dataset", VALORANT_RESULTS, retrieved, None, raw, "UNVERIFIABLE")
    return added


def html_to_text(text):
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text, flags=re.I)
    text = re.sub(r"&amp;", "&", text, flags=re.I)
    return clean(text)


def backfill_rizin(c, max_pages=150):
    index, _, _ = http(RIZIN_TAG)
    # Handle both absolute and relative article links. The previous parser only
    # matched one HTML shape and could silently return zero events.
    urls = set(re.findall(r"https?://jp\.rizinff\.com/_ct/\d+", index))
    urls.update(urljoin(RIZIN_TAG, x) for x in re.findall(r"(?:href|data-href)=[\"']([^\"']*/_ct/\d+)[\"']", index, re.I))
    urls.update(urljoin(RIZIN_TAG, x) for x in re.findall(r"(/_ct/\d+)", index))
    added = 0
    for url in sorted(urls)[:max_pages]:
        try:
            text, rr, _ = http(url)
        except Exception:
            continue
        plain = html_to_text(text)
        title_match = re.search(r"([^\n]{2,120})試合結果(?:一覧)?", plain)
        title = clean(title_match.group(1) if title_match else url)
        date_match = re.search(r"(20\d{2})\s*[年/.-]\s*(\d{1,2})\s*[月/.-]\s*(\d{1,2})", plain)
        et = iso("-".join(date_match.groups())) if date_match else None

        pairs = []
        patterns = [
            r"(?:\(WIN\)|WIN)\s*([^()\n]{1,80}?)\s+(?:vs\.?|VS|対|vs)\s+([^()\n]{1,80}?)\s*(?:\(LOSE\)|LOSE)",
            r"(?:\(LOSE\)|LOSE)\s*([^()\n]{1,80}?)\s+(?:vs\.?|VS|対|vs)\s+([^()\n]{1,80}?)\s*(?:\(WIN\)|WIN)",
            r"([^()\n]{1,80}?)\s+(?:vs\.?|VS)\s+([^()\n]{1,80}?)\s+(?:WIN|LOSE)",
        ]
        for pat in patterns:
            pairs.extend(re.findall(pat, plain, re.I))

        # Japanese result pages sometimes expose winner/loser as adjacent text
        # without a literal 'vs'. Keep this fallback conservative to avoid
        # turning headings/navigation into fake fights.
        if not pairs:
            lines = [clean(x) for x in re.split(r"[\n|]", plain) if clean(x)]
            for i, line in enumerate(lines):
                if re.search(r"\b(WIN|LOSE)\b|勝者|敗者", line, re.I) and i + 1 < len(lines):
                    nxt = lines[i + 1]
                    if 2 <= len(line) <= 100 and 2 <= len(nxt) <= 100 and not re.search(r"試合結果|RIZIN|ROUND|大会", line, re.I):
                        pairs.append((re.sub(r"\b(WIN|LOSE)\b|勝者|敗者", "", line, flags=re.I), nxt))

        seen_pairs = set()
        for a, b in pairs:
            a, b = clean(a), clean(b)
            a = re.sub(r"^(?:\(WIN\)|WIN|勝者)\s*", "", a, flags=re.I)
            b = re.sub(r"(?:\(LOSE\)|LOSE|敗者)\s*$", "", b, flags=re.I)
            if not a or not b or len(a) > 80 or len(b) > 80 or a == b:
                continue
            key = (a, b, et, url)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            eid = upsert_event(c, "rizin", f"{a} vs {b}", et, "jp.rizinff.com", url, "COMPLETED",
                               competition=title, season=str(et)[:4] if et else None)
            p1 = upsert_participant(c, "rizin", a, "fighter")
            p2 = upsert_participant(c, "rizin", b, "fighter")
            upsert_ep(c, eid, p1, p1, "A", "fight", "jp.rizinff.com", url)
            upsert_ep(c, eid, p2, p2, "B", "fight", "jp.rizinff.com", url)
            # Do not infer a winner from page order unless an explicit marker
            # is present near the fighter names.
            local = plain[max(0, plain.find(a) - 120):plain.find(b) + 160]
            if re.search(r"(?:\(WIN\)|\bWIN\b|勝者).*?" + re.escape(a), local, re.I | re.S):
                side = "A"
            elif re.search(r"(?:\(WIN\)|\bWIN\b|勝者).*?" + re.escape(b), local, re.I | re.S):
                side = "B"
            else:
                # If the pattern explicitly had WIN first / LOSE second, that
                # is sufficient; otherwise leave the event without a label.
                if re.search(r"WIN.*?vs.*?LOSE", plain[max(0, plain.find(a)-40):plain.find(b)+100], re.I | re.S):
                    side = "A"
                elif re.search(r"LOSE.*?vs.*?WIN", plain[max(0, plain.find(a)-40):plain.find(b)+100], re.I | re.S):
                    side = "B"
                else:
                    side = None
            if side:
                outcome(c, "rizin", eid, p1, p2, side, url)
            added += 1
        if pairs:
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
            text, retrieved, _ = http(url)
        except Exception:
            continue
        links = set(re.findall(r"https://en\.volleyballworld\.com/volleyball/[^\s)\"<>]+", text))
        for link in links:
            if re.search(r"/matches?/|/competitions/", link, re.I) and link not in seen:
                queue.append(link)
        matches = re.findall(r'"name"\s*:\s*"([^"]+)".{0,500}?"startDate"\s*:\s*"([^"]+)"', text, re.S)
        for name, dt in matches:
            if " vs " not in name.lower() and " v " not in name.lower():
                continue
            et = iso(dt)
            if not et:
                continue
            parts = re.split(r"\s+v(?:s\.?|)\s+", clean(name), maxsplit=1, flags=re.I)
            if len(parts) != 2:
                continue
            a, b = clean(parts[0]), clean(parts[1])
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
    out, warnings = {}, []
    try:
        for sport in [x.strip() for x in a.sports.split(",") if x.strip()]:
            try:
                if sport == "valorant":
                    out[sport] = backfill_valorant(c)
                elif sport == "basketball":
                    for key, url, comp in (
                        ("nba", NBA_GAMES, "NBA"),
                        ("wnba", WNBA_GAMES, "WNBA"),
                        ("fiba_world_cup_2019", FIBA_2019, "FIBA World Cup 2019"),
                    ):
                        try:
                            out[key] = backfill_csv_games(c, url, "basketball", comp)
                        except Exception as e:
                            warnings.append({"source": key, "error": repr(e)})
                elif sport == "rizin":
                    out[sport] = backfill_rizin(c)
                elif sport == "volleyball":
                    out[sport] = backfill_volleyball(c)
                else:
                    warnings.append({"sport": sport, "error": "unsupported public fallback"})
            except Exception as e:
                warnings.append({"sport": sport, "error": repr(e)})
        c.commit()
    finally:
        c.close()
    report = {
        "parser_version": "v4.5.15-public-history",
        "added": out,
        "warnings": warnings,
        "timestamp_utc": utcnow(),
    }
    pth = ROOT / "results" / "public_history_backfill.json"
    pth.parent.mkdir(parents=True, exist_ok=True)
    pth.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Availability remains non-blocking here; quality/release gates decide
    # whether incomplete historical coverage is acceptable for production.
    raise SystemExit(0)


if __name__ == "__main__":
    main()
