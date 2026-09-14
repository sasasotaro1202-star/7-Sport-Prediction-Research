from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.seven_sport_production import add_snapshot, add_stat, upsert_ep, upsert_event, upsert_participant
from src.storage.db_v45 import connect, utcnow

ROOT = Path(__file__).resolve().parents[1]
# Jeff Sackmann's upstream GitHub repositories became unavailable in 2026.
# Use a citable archival mirror that preserves the upstream files/provenance.
ARCHIVE_ROOT = "https://raw.githubusercontent.com/Aneeshers/tennis-sackmann-archive/main"
ATP = f"{ARCHIVE_ROOT}/atp/atp_matches_{{year}}.csv"
WTA = f"{ARCHIVE_ROOT}/wta/wta_matches_{{year}}.csv"
PARSER_VERSION = "v4.6.1-tennis-archive-pit"
SOURCE_NAME = "JeffSackmannArchive"


def dt(v):
    s = str(v or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    return None


def fetch(url):
    retrieved = utcnow()
    r = requests.get(url, headers={"User-Agent": "SevenSportResearchEngine/4.6"}, timeout=30)
    r.raise_for_status()
    return r.text, retrieved


def load(c, url, tour, year):
    source_url = url.format(year=year)
    raw, retrieved = fetch(source_url)
    payload_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    # Retrieval time is the conservative source availability timestamp. We never
    # pretend the archival file was available at the historical match time.
    add_snapshot(c, "tennis", SOURCE_NAME, source_url, retrieved, None, payload_hash, "VERIFIED_ARCHIVE_RETRIEVAL")

    rows = csv.DictReader(io.StringIO(raw))
    n = 0
    for row in rows:
        winner = (row.get("winner_name") or "").strip()
        loser = (row.get("loser_name") or "").strip()
        if not winner or not loser:
            continue
        et = dt(row.get("tourney_date"))
        tournament = (row.get("tourney_name") or "").strip()
        surface = (row.get("surface") or "").strip()
        rnd = (row.get("round") or "").strip()
        eid = upsert_event(
            c, "tennis", f"{winner} vs {loser}", et, SOURCE_NAME, source_url,
            "COMPLETED", competition=tournament or tour, stage=rnd or None, season=str(year)
        )
        p1 = upsert_participant(c, "tennis", winner, "player")
        p2 = upsert_participant(c, "tennis", loser, "player")
        upsert_ep(c, eid, p1, p1, "A", "match", SOURCE_NAME, source_url)
        upsert_ep(c, eid, p2, p2, "B", "match", SOURCE_NAME, source_url)
        c.execute(
            """INSERT OR REPLACE INTO event_outcome
            (event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,outcome_status,source,source_url,observed_at_utc,quality_status,reason)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                eid, "tennis", p1, p2, "A", None, None, "VERIFIED", SOURCE_NAME,
                source_url, utcnow(), "PIT_REQUIRES_REPLAY",
                "Historical match label; post-event archive is never used as pre-match feature evidence.",
            ),
        )
        score = (row.get("score") or "").strip()
        if score:
            add_stat(c, eid, p1, p1, "tennis", "match.score", 0.0, score, SOURCE_NAME, source_url)
        if surface:
            add_stat(c, eid, p1, p1, "tennis", "surface", 0.0, surface, SOURCE_NAME, source_url)
        for key in (
            "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon",
            "w_bpSaved", "w_bpFaced", "l_ace", "l_df", "l_svpt", "l_1stIn",
            "l_1stWon", "l_2ndWon", "l_bpSaved", "l_bpFaced",
        ):
            try:
                value = float(row.get(key))
            except (TypeError, ValueError):
                continue
            pid = p1 if key.startswith("w_") else p2
            add_stat(c, eid, pid, pid, "tennis", key, value, str(value), SOURCE_NAME, source_url)
        n += 1
    return n


def main():
    c = connect()
    added = {}
    warnings = []
    try:
        current_year = datetime.now(timezone.utc).year
        for tour, url in (("ATP", ATP), ("WTA", WTA)):
            total = 0
            for year in range(2016, current_year + 1):
                state_key = f"tennis-public:{tour}:{year}"
                row = c.execute("SELECT completed FROM collection_state WHERE state_key=?", (state_key,)).fetchone()
                if row and bool(row[0]) and year < current_year:
                    continue
                try:
                    n = load(c, url, tour, year)
                    total += n
                    c.execute(
                        """INSERT INTO collection_state
                        (state_key,sport,scope,cursor,completed,updated_at_utc,metadata_json)
                        VALUES(?,?,?,?,?,?,?)
                        ON CONFLICT(state_key) DO UPDATE SET
                          cursor=excluded.cursor, completed=excluded.completed,
                          updated_at_utc=excluded.updated_at_utc, metadata_json=excluded.metadata_json""",
                        (state_key, "tennis", f"public:{tour}:{year}", str(year), 1, utcnow(),
                         json.dumps({"rows": n, "parser_version": PARSER_VERSION, "source": SOURCE_NAME}, ensure_ascii=False)),
                    )
                    c.commit()
                except Exception as e:
                    c.rollback()
                    warnings.append({"tour": tour, "year": year, "source_url": url.format(year=year), "error": repr(e)})
            added[tour] = total
        c.commit()
    finally:
        c.close()
    report = {"parser_version": PARSER_VERSION, "source": SOURCE_NAME, "added": added, "warnings": warnings, "timestamp_utc": utcnow()}
    p = ROOT / "results" / "tennis_public_backfill.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
