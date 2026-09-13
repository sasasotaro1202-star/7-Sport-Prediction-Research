from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.seven_sport_production import add_stat, upsert_ep, upsert_event, upsert_participant
from src.storage.db_v45 import connect, utcnow

ROOT = Path(__file__).resolve().parents[1]
ATP = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_matches_{year}.csv"
WTA = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/wta_matches_{year}.csv"


def dt(v):
    s = str(v or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    return None


def fetch(url):
    h = {"User-Agent": "SevenSportResearchEngine/4.5.14"}
    r = requests.get(url, headers=h, timeout=30)
    r.raise_for_status()
    return r.text


def load(c, url, tour, year):
    raw = fetch(url.format(year=year))
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
        eid = upsert_event(c, "tennis", f"{winner} vs {loser}", et, "JeffSackmann", url.format(year=year), "COMPLETED", competition=tournament or tour, stage=rnd or None, season=str(year))
        p1 = upsert_participant(c, "tennis", winner, "player")
        p2 = upsert_participant(c, "tennis", loser, "player")
        upsert_ep(c, eid, p1, p1, "A", "match", "JeffSackmann", url.format(year=year))
        upsert_ep(c, eid, p2, p2, "B", "match", "JeffSackmann", url.format(year=year))
        c.execute("""INSERT OR REPLACE INTO event_outcome
            (event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,outcome_status,source,source_url,observed_at_utc,quality_status,reason)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (eid,"tennis",p1,p2,"A",None,None,"VERIFIED","JeffSackmann",url.format(year=year),utcnow(),"PIT_REQUIRES_REPLAY","Historical match label; post-event source is never used as pre-match feature evidence."))
        score = (row.get("score") or "").strip()
        if score:
            add_stat(c,eid,p1,p1,"tennis","match.score",0.0,score,"JeffSackmann",url.format(year=year))
        if surface:
            add_stat(c,eid,p1,p1,"tennis","surface",0.0,surface,"JeffSackmann",url.format(year=year))
        for key in ("w_ace","w_df","w_svpt","w_1stIn","w_1stWon","w_2ndWon","w_bpSaved","w_bpFaced","l_ace","l_df","l_svpt","l_1stIn","l_1stWon","l_2ndWon","l_bpSaved","l_bpFaced"):
            try:
                value = float(row.get(key))
            except (TypeError, ValueError):
                continue
            pid = p1 if key.startswith("w_") else p2
            add_stat(c,eid,pid,pid,"tennis",key,value,str(value),"JeffSackmann",url.format(year=year))
        n += 1
    return n


def main():
    c = connect()
    added = {}
    warnings = []
    try:
        for tour, url in (("ATP",ATP),("WTA",WTA)):
            total = 0
            for year in range(2016, 2027):
                try:
                    total += load(c,url,tour,year)
                except Exception as e:
                    warnings.append({"tour":tour,"year":year,"error":repr(e)})
            added[tour] = total
        c.commit()
    finally:
        c.close()
    report={"parser_version":"v4.5.14-tennis-public","added":added,"warnings":warnings,"timestamp_utc":utcnow()}
    p=ROOT/"results"/"tennis_public_backfill.json"
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
