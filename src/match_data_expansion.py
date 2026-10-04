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
PARSER_VERSION = "match-data-expansion-v3-participant-profile-pit"
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




def _label_value_lines(html: str):
    soup = BeautifulSoup(html, "lxml")
    return [clean(x) for x in soup.get_text("\n").splitlines() if clean(x)]


def parse_fiba_game_detail(html: str):
    lines = _label_value_lines(html)
    text = " ".join(lines)
    result = {
        "game_stage": None,
        "group": None,
        "teams": [],
        "quarter_scores": [],
        "game_stats": {},
        "attendance": None,
        "score_a": None,
        "score_b": None,
    }
    m = re.search(r"(Group Phase|Class\.\s*\d+[\-–]\d+|Round of 16|Quarterfinals|Semifinals|Final)", text, re.I)
    if m:
        result["game_stage"] = clean(m.group(1))
    m = re.search(r"Group\s+([A-Z])\b", text, re.I)
    if m:
        result["group"] = m.group(1)
    score_tokens = re.findall(r"\b(\d+)\s*[–-]\s*(\d+)\b", text)
    if score_tokens:
        result["score_a"], result["score_b"] = map(int, score_tokens[0])
    for line in lines:
        m = re.search(r"Attendance\s+(\d[\d,]*)", line, re.I)
        if m:
            result["attendance"] = int(m.group(1).replace(",", ""))
    stat_patterns = {
        "fg_pct": re.compile(r"FG\s*%", re.I),
        "2pt_fg_pct": re.compile(r"2PT\s*FG", re.I),
        "3pt_fg_pct": re.compile(r"3PT\s*FG", re.I),
        "ft_pct": re.compile(r"FT\s*%", re.I),
    }
    for key, pattern in stat_patterns.items():
        idx = next((i for i, line in enumerate(lines) if pattern.search(line)), None)
        if idx is None:
            continue
        nums = [
            float(x)
            for x in re.findall(
                r"(?<!\d)(\d+(?:\.\d+)?)%(?!\d)",
                lines[idx],
            )
        ]
        if len(nums) < 2:
            for next_idx in range(idx + 1, min(len(lines), idx + 3)):
                candidate = lines[next_idx]
                if any(
                    other.search(candidate)
                    for other in stat_patterns.values()
                    if other is not pattern
                ):
                    break
                nums.extend(
                    float(x)
                    for x in re.findall(
                        r"(?<!\d)(\d+(?:\.\d+)?)%(?!\d)",
                        candidate,
                    )
                )
                if len(nums) >= 2:
                    break
        if nums:
            result["game_stats"][key] = nums[:2]
    return result


def parse_volleyball_detail(html: str):
    lines = _label_value_lines(html)
    text = " ".join(lines)
    result = {
        "status": None,
        "venue": None,
        "match_stage": None,
        "score": None,
    }
    for status in ("LIVE", "Scheduled", "Final", "Finished", "Postponed", "Cancelled"):
        if re.search(rf"\b{re.escape(status)}\b", text, re.I):
            result["status"] = status.upper()
            break
    for token in ("Quarterfinal", "Semifinal", "Final", "Pool", "Group"):
        m = re.search(rf"([^|\n]{{0,80}}\b{token}[^|\n]{{0,80}})", text, re.I)
        if m:
            result["match_stage"] = clean(m.group(1))
            break
    # Prefer the label-preserving lines so adjacent HTML blocks such as
    # "Venue: Ariake Arena" followed by "25-22" cannot be conflated.
    label = re.compile(r"^(?:Venue|Location|Host City)\s*[:：]?\s*(.*)$", re.I)
    for index, line in enumerate(lines):
        m = label.search(line)
        if not m:
            continue
        venue = clean(m.group(1))
        if not venue and index + 1 < len(lines):
            venue = clean(lines[index + 1])
        # Some pages render score text in the same block as the venue. Bound the
        # capture before a volleyball score rather than persisting adjacent data.
        venue = re.split(
            r"\s+\b\d{1,2}\s*[-–:]\s*\d{1,2}\b",
            venue,
            maxsplit=1,
        )[0]
        if venue:
            result["venue"] = venue
            break
    pairs = re.findall(r"\b(\d{1,2})\s*[-–:]\s*(\d{1,2})\b", text)
    if pairs:
        result["score"] = [int(pairs[0][0]), int(pairs[0][1])]
    return result


def parse_ufcstats_detail(html: str):
    lines = _label_value_lines(html)
    text = " ".join(lines)
    result = {
        "height": None,
        "weight": None,
        "reach": None,
        "stance": None,
        "dob": None,
        "career_stats": {},
        "has_matchup_preview": "Matchup Preview" in text,
        "next_opponent": None,
    }
    patterns = {
        "height": r"Height\s*:\s*([^|]+?)(?=\s+Weight\s*:)",
        "weight": r"Weight\s*:\s*([^|]+?)(?=\s+Reach\s*:)",
        "reach": r"Reach\s*:\s*([^|]+?)(?=\s+STANCE\s*:)",
        "stance": r"STANCE\s*:\s*([A-Za-z]+)",
        "dob": r"DOB\s*:\s*([A-Za-z]+\.?\s+\d{1,2},\s+\d{4})",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, re.I)
        if m:
            result[key] = clean(m.group(1))
    stat_patterns = {
        "SLpM": r"SLpM\s*:\s*([\d.]+)",
        "Str_Acc": r"Str\.\s*Acc\.\s*:\s*(\d+%)",
        "SApM": r"SApM\s*:\s*([\d.]+)",
        "Str_Def": r"Str\.\s*Def\s*:\s*(\d+%)",
        "TD_Avg": r"TD\s*Avg\.\s*:\s*([\d.]+)",
        "TD_Acc": r"TD\s*Acc\.\s*:\s*(\d+%)",
        "TD_Def": r"TD\s*Def\.?\s*:\s*(\d+%)",
        "Sub_Avg": r"Sub\.\s*Avg\s*:\s*([\d.]+)",
    }
    for key, pat in stat_patterns.items():
        m = re.search(pat, text, re.I)
        if m:
            value = m.group(1)
            try:
                result["career_stats"][key] = float(value.rstrip("%"))
            except Exception:
                result["career_stats"][key] = value
    return result


def parse_rizin_detail(html: str):
    lines = _label_value_lines(html)
    text = " ".join(lines)
    result = {
        "rule": None,
        "contract_weight_kg": None,
        "weight_class_text": None,
        "cancelled": False,
        "change_notice": False,
        "method": None,
        "round": None,
        "time": None,
    }
    m = re.search(
        r"(RIZIN\s+(?:MMA|キックボクシング|KICKBOXING)[^|]*?ルール[^|]*)",
        text,
        re.I,
    )
    if m:
        rule_text = clean(m.group(1))
        result["rule"] = rule_text
        weight = re.search(
            r"[（(]\s*(\d+(?:\.\d+)?)\s*kg\s*[）)]",
            rule_text,
            re.I,
        )
        if weight:
            result["contract_weight_kg"] = float(weight.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)kg\s*契約(?:マッチ|戦)?", text, re.I)
    if m:
        result["contract_weight_kg"] = float(m.group(1))
        result["weight_class_text"] = clean(m.group(0))
    result["cancelled"] = bool(re.search(r"(?:試合|対戦)[^。]{0,40}中止|中止となりました|CANCELLED", text, re.I))
    result["change_notice"] = bool(re.search(r"変更のお知らせ|変更情報|updated|change", text, re.I))
    m = re.search(r"\b(\d+)R\s+(\d+)分\s*(\d+)秒\s+([^|]+)", text)
    if m:
        result["round"] = int(m.group(1))
        result["time"] = f"{int(m.group(2))}:{int(m.group(3)):02d}"
        result["method"] = clean(m.group(4))
    return result


def _write_key_values(con, event, values, source, retrieved, exact):
    written = 0
    for stat_name, (num, text_value) in values.items():
        if num is None and not text_value:
            continue
        _insert_stat(
            con, event["event_id"], None, None, event["sport"], stat_name,
            num, text_value, source, event["source_url"],
            retrieved.isoformat(),
            retrieved.isoformat() if exact else None,
            "EXACT" if exact else "UNVERIFIABLE",
        )
        written += 1
    return written


def _ufcstats_profile_links(html):
    soup = BeautifulSoup(html, "lxml")
    out = {}
    for node in soup.select("a[href*='/fighter-details/']"):
        name = clean(node.get_text(" ", strip=True))
        href = clean(node.get("href"))
        if not name or not href:
            continue
        if href.startswith("/"):
            href = "https://ufcstats.com" + href
        if "ufcstats.com/fighter-details/" not in href:
            continue
        out[name.casefold()] = href
    return out


def _ufc_profile_number(kind, raw):
    if raw is None:
        return None
    text = clean(raw)
    if not text:
        return None
    if kind == "height_cm":
        m = re.search(r"(\d+)\s*['’]\s*(\d+(?:\.\d+)?)?\s*(?:\\"|in)?", text)
        if m:
            return float(m.group(1)) * 30.48 + float(m.group(2) or 0.0) * 2.54
    if kind == "weight_kg":
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:lb|lbs|pounds)", text, re.I)
        if m:
            return float(m.group(1)) * 0.45359237
    if kind == "reach_cm":
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:\\"|in|inch|inches)", text, re.I)
        if m:
            return float(m.group(1)) * 2.54
    m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(m.group()) if m else None


def _record_triplet(html):
    text = " ".join(_label_value_lines(html))
    m = re.search(r"Record\s*:\s*(\d+)-(\d+)-(\d+)", text, re.I)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _write_ufc_participant_profile_history(con, event, event_html, event_retrieved, lead_minutes):
    """Persist fighter profile observations against canonical participant IDs.

    Profiles are only eligible for research/prediction when the fighter-profile
    page itself was observed no later than the event cutoff. A late observation
    is retained as UNVERIFIABLE evidence but never exposed by the PIT feature
    loader.
    """
    if event.get("sport") != "ufc":
        return 0
    participants = _participants(con, event["event_id"])
    if len(participants) < 2:
        return 0
    links = _ufcstats_profile_links(event_html)
    if not links and "/fighter-details/" in str(event.get("source_url") or ""):
        links = {}
    written = 0
    event_time = _dt(event.get("event_time_utc"))
    if event_time is None:
        return 0
    cutoff = event_time - timedelta(minutes=int(lead_minutes))
    for side, pid, _team_id, canonical_name in participants:
        profile_url = links.get(str(canonical_name or "").casefold())
        if not profile_url:
            continue
        try:
            raw, profile_retrieved, _ = _http_get(profile_url)
        except Exception:
            continue
        exact, available_at = _exact_for_cutoff(profile_retrieved, event_time, lead_minutes)
        content_hash = hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()
        add_snapshot(
            con,
            "ufc",
            "ufcstats-fighter-profile",
            profile_url,
            profile_retrieved.isoformat(),
            event["event_time_utc"],
            content_hash,
            "EXACT" if exact else "UNVERIFIABLE",
            source_available_at_utc=available_at,
            provenance={
                "sport": "ufc",
                "participant_id": pid,
                "participant_side": side,
                "parser": PARSER_VERSION,
                "evidence": "prospective_fighter_profile_observation" if exact else "late_fighter_profile_observation",
                "prediction_lead_minutes": int(lead_minutes),
            },
        )
        data = parse_ufcstats_detail(raw)
        values = {
            "height_cm": (_ufc_profile_number("height_cm", data.get("height")), None),
            "weight_kg": (_ufc_profile_number("weight_kg", data.get("weight")), None),
            "reach_cm": (_ufc_profile_number("reach_cm", data.get("reach")), None),
            "dob": (None, data.get("dob")),
            "stance": (None, data.get("stance")),
        }
        rec = _record_triplet(raw)
        if rec:
            values.update({
                "career_wins": (float(rec[0]), None),
                "career_losses": (float(rec[1]), None),
                "career_draws": (float(rec[2]), None),
            })
        for key, value in data.get("career_stats", {}).items():
            if isinstance(value, (int, float)):
                values[f"fighter.career_{key.lower()}"] = (float(value), None)
        for attribute, (value_num, value_text) in values.items():
            if value_num is None and not value_text:
                continue
            history_id = sid(
                PARSER_VERSION,
                pid,
                event["event_id"],
                attribute,
                value_num,
                value_text,
                profile_url,
                profile_retrieved.isoformat(),
            )
            con.execute(
                """
                INSERT OR REPLACE INTO participant_history(
                  history_id,participant_id,sport,event_id,observed_at_utc,
                  effective_at_utc,attribute,value_text,value_num,value_json,
                  source,source_url,quality_status,confidence
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    history_id, pid, "ufc", event["event_id"],
                    profile_retrieved.isoformat(),
                    profile_retrieved.isoformat(),
                    attribute, value_text, value_num, None,
                    "ufcstats-fighter-profile", profile_url,
                    "EXACT" if exact else "UNVERIFIABLE",
                    1.0 if exact else 0.0,
                ),
            )
            written += 1
    return written


def _write_source_specific_detail(con, event, html, retrieved, source, exact):
    host = urlparse(event["source_url"]).netloc.lower()
    if "fiba.basketball" in host:
        data = parse_fiba_game_detail(html)
        values = {
            "match.fiba.stage": (None, data.get("game_stage")),
            "match.fiba.group": (None, data.get("group")),
            "match.fiba.attendance": (
                float(data["attendance"]) if data.get("attendance") is not None else None,
                None,
            ),
            "match.fiba.score_a": (
                float(data["score_a"]) if data.get("score_a") is not None else None,
                None,
            ),
            "match.fiba.score_b": (
                float(data["score_b"]) if data.get("score_b") is not None else None,
                None,
            ),
        }
        for key, pair in data.get("game_stats", {}).items():
            vals = pair[:2]
            values[f"match.fiba.{key}.a"] = (vals[0], None) if len(vals) > 0 else (None, None)
            values[f"match.fiba.{key}.b"] = (vals[1], None) if len(vals) > 1 else (None, None)
        return _write_key_values(con, event, values, source, retrieved, exact)

    if "volleyballworld.com" in host:
        data = parse_volleyball_detail(html)
        values = {
            "match.volleyball.status": (None, data.get("status")),
            "match.volleyball.venue": (None, data.get("venue")),
            "match.volleyball.stage": (None, data.get("match_stage")),
            "match.volleyball.score_a": (
                float(data["score"][0]), None
            ) if data.get("score") else (None, None),
            "match.volleyball.score_b": (
                float(data["score"][1]), None
            ) if data.get("score") else (None, None),
        }
        return _write_key_values(con, event, values, source, retrieved, exact)

    if "ufcstats.com" in host:
        data = parse_ufcstats_detail(html)
        values = {
            "fighter.height": (None, data.get("height")),
            "fighter.weight": (None, data.get("weight")),
            "fighter.reach": (None, data.get("reach")),
            "fighter.stance": (None, data.get("stance")),
            "fighter.dob": (None, data.get("dob")),
            "match.ufc.has_matchup_preview": (
                1.0 if data.get("has_matchup_preview") else 0.0,
                None,
            ),
            "match.ufc.next_opponent": (None, data.get("next_opponent")),
        }
        for key, value in data.get("career_stats", {}).items():
            if isinstance(value, (int, float)):
                values[f"fighter.career_{key.lower()}"] = (float(value), None)
        return _write_key_values(con, event, values, source, retrieved, exact)

    if "jp.rizinff.com" in host:
        data = parse_rizin_detail(html)
        values = {
            "match.rizin.rule": (None, data.get("rule")),
            "match.rizin.contract_weight_kg": (data.get("contract_weight_kg"), None),
            "match.rizin.weight_class_text": (None, data.get("weight_class_text")),
            "match.rizin.cancelled": (1.0 if data.get("cancelled") else 0.0, None),
            "match.rizin.change_notice": (1.0 if data.get("change_notice") else 0.0, None),
            "match.rizin.method": (None, data.get("method")),
            "match.rizin.round": (
                float(data["round"]) if data.get("round") is not None else None,
                None,
            ),
            "match.rizin.time": (None, data.get("time")),
        }
        return _write_key_values(con, event, values, source, retrieved, exact)

    return 0


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

        written = _write_jsonld(con, event, raw, retrieved, source, exact)
        if event["sport"] == "basketball" and "bleague.jp" in url:
            written += _write_bleague(con, event, raw, retrieved, exact)
        written += _write_source_specific_detail(
            con, event, raw, retrieved, source, exact
        )
        if event["sport"] == "ufc":
            written += _write_ufc_participant_profile_history(
                con, event, raw, retrieved, lead_minutes
            )

        return {
            "status": "OK",
            "event_id": event["event_id"],
            "source": source,
            "exact": exact,
            "available_at": available_at,
            "written_stats": written,
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
        SELECT
            e.event_id,
            e.sport,
            e.event_time_utc,
            e.event_type,
            e.status,
            (
                SELECT ep.source_url
                  FROM event_participant ep
                 WHERE ep.event_id=e.event_id
                   AND ep.source_url IS NOT NULL
                 ORDER BY CASE ep.side WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END,
                          ep.source_url
                 LIMIT 1
            ) AS source_url
          FROM event e
         WHERE e.sport=?
           AND e.event_time_utc IS NOT NULL
           AND datetime(e.event_time_utc) > datetime(?)
           AND datetime(e.event_time_utc) <= datetime(?)
           AND UPPER(COALESCE(e.status,'')) NOT IN ('CANCELLED','VOID')
           AND EXISTS (
                SELECT 1
                  FROM event_participant ep2
                 WHERE ep2.event_id=e.event_id
                   AND ep2.source_url IS NOT NULL
           )
         ORDER BY datetime(e.event_time_utc), e.event_id
         LIMIT ?
        """,
        (sport, lower.isoformat(), upper.isoformat(), int(max_events)),
    ).fetchall()


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
        con.commit()
    after = con.execute(
        "SELECT COUNT(*) FROM match_stats WHERE sport=?",
        (sport,),
    ).fetchone()[0]
    con.close()
    return {
        "parser_version": PARSER_VERSION,
        "sport": sport,
        "selected_events": len(selected),
        "skipped_fresh": skipped_fresh,
        "processed_events": len(results),
        "fetch_errors": errors,
        "new_match_stats": after - before,
        "results": results,
        # Any fetch error on a selected future event is a real enrichment failure.
        # A partially successful batch must not be mislabeled as fully successful.
        "status": "DEGRADED" if errors else "OK",
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
    return 1 if report["status"] == "DEGRADED" else 0


if __name__ == "__main__":
    main()
