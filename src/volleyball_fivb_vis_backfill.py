from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

from src.seven_sport_production import add_snapshot, add_stat, upsert_ep, upsert_event, upsert_participant
from src.storage.db_v45 import connect, utcnow

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://www.fivb.org/Vis2009/XmlRequest.asmx"
PARSER_VERSION = "v4.6.1-fivb-vis-match-list"


def iso(v):
    s = str(v or "").strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def sid(*parts):
    return hashlib.sha256("|".join("" if x is None else str(x) for x in parts).encode()).hexdigest()[:32]


def request_year(year: int):
    xml = (
        "<Request Type='GetVolleyMatchList' "
        "Fields='No NoInTournament DateTimeLocal DateTimeUtc MatchPointsA MatchPointsB Status'>"
        f"<Filter FirstDate='{year}-01-01' LastDate='{year}-12-31' />"
        "<Relation Name='TeamA' Fields='Code Name' />"
        "<Relation Name='TeamB' Fields='Code Name' />"
        "<Relation Name='Tournament' Fields='Code Name' />"
        "</Request>"
    )
    r = requests.post(
        ENDPOINT,
        data={"Request": xml},
        headers={
            "User-Agent": "SevenSportResearchEngine/4.6",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        },
        timeout=45,
    )
    r.raise_for_status()
    return r.json()


def parse_matches(payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        return data
    # Defensive XML fallback for servers/proxies that ignore Accept: application/json.
    text = payload if isinstance(payload, str) else ""
    if not text:
        return []
    root = ET.fromstring(text)
    out = []
    for node in root.findall(".//VolleyballMatch"):
        def rel(name):
            x = node.find(name)
            return {k: v for k, v in x.attrib.items()} if x is not None else {}
        out.append({
            "no": node.attrib.get("No"),
            "dateTimeUtc": node.attrib.get("DateTimeUtc"),
            "dateTimeLocal": node.attrib.get("DateTimeLocal"),
            "matchPointsA": node.attrib.get("MatchPointsA"),
            "matchPointsB": node.attrib.get("MatchPointsB"),
            "teamA": rel("TeamA"),
            "teamB": rel("TeamB"),
            "tournament": rel("Tournament"),
        })
    return out


def load_year(c, year):
    payload = request_year(year)
    matches = parse_matches(payload)
    added = 0
    for m in matches:
        a = (m.get("teamA") or {}).get("name") or ""
        b = (m.get("teamB") or {}).get("name") or ""
        if not a or not b:
            continue
        et = iso(m.get("dateTimeUtc") or m.get("dateTimeLocal"))
        tour = (m.get("tournament") or {}).get("name") or "FIVB"
        source_url = ENDPOINT
        eid = upsert_event(c, "volleyball", f"{a} vs {b}", et, "FIVB_VIS", source_url,
                           "COMPLETED", competition=tour, season=str(year))
        p1 = upsert_participant(c, "volleyball", a, "team")
        p2 = upsert_participant(c, "volleyball", b, "team")
        upsert_ep(c, eid, p1, p1, "A", "match", "FIVB_VIS", source_url)
        upsert_ep(c, eid, p2, p2, "B", "match", "FIVB_VIS", source_url)
        try:
            sa, sb = float(m.get("matchPointsA")), float(m.get("matchPointsB"))
        except (TypeError, ValueError):
            sa = sb = None
        if sa is not None and sb is not None:
            side = "A" if sa > sb else "B" if sb > sa else "DRAW"
            c.execute(
                """INSERT OR REPLACE INTO event_outcome
                (event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,
                 outcome_status,source,source_url,observed_at_utc,quality_status,reason)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (eid, "volleyball", p1, p2, side, sa, sb, "VERIFIED", "FIVB_VIS", source_url,
                 utcnow(), "PIT_REQUIRES_REPLAY", "Historical FIVB result; publication timing requires replay."),
            )
            add_stat(c, eid, p1, p1, "volleyball", "sets.final", sa, str(sa), "FIVB_VIS", source_url)
            add_stat(c, eid, p2, p2, "volleyball", "sets.final", sb, str(sb), "FIVB_VIS", source_url)
        added += 1
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    add_snapshot(c, "volleyball", "FIVB_VIS", source_url, utcnow(), None,
                 hashlib.sha256(raw.encode()).hexdigest(), "UNVERIFIABLE")
    return added


def main():
    c = connect()
    added = {}
    warnings = []
    current_year = datetime.now(timezone.utc).year
    try:
        for year in range(2016, current_year + 1):
            state_key = f"volleyball-fivb:{year}"
            row = c.execute("SELECT completed FROM collection_state WHERE state_key=?", (state_key,)).fetchone()
            if row and bool(row[0]) and year < current_year:
                continue
            try:
                n = load_year(c, year)
                added[str(year)] = n
                c.execute(
                    """INSERT INTO collection_state(state_key,sport,scope,cursor,completed,updated_at_utc,metadata_json)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(state_key) DO UPDATE SET cursor=excluded.cursor, completed=excluded.completed,
                    updated_at_utc=excluded.updated_at_utc, metadata_json=excluded.metadata_json""",
                    (state_key, "volleyball", f"fivb:{year}", str(year), 1, utcnow(),
                     json.dumps({"rows": n, "parser_version": PARSER_VERSION})),
                )
                c.commit()
            except Exception as exc:
                c.rollback()
                warnings.append({"year": year, "error": repr(exc)})
    finally:
        c.close()
    report = {"parser_version": PARSER_VERSION, "added": added, "warnings": warnings, "timestamp_utc": utcnow()}
    p = ROOT / "results" / "volleyball_fivb_vis_backfill.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
