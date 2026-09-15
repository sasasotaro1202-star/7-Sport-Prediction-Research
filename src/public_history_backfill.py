from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from src.storage.db_v45 import connect, utcnow
from src.seven_sport_production import add_snapshot, add_stat, upsert_ep, upsert_event, upsert_participant

ROOT = Path(__file__).resolve().parents[1]
VALORANT_RESULTS = "https://raw.githubusercontent.com/rush2pranav/valorant-pro-scene-tracker/main/data/results.csv"


def clean(v):
    import re
    return re.sub(r"\s+", " ", str(v or "")).strip()


def iso(v):
    from datetime import datetime, timezone
    if v is None or str(v).strip() == "":
        return None
    s = str(v).strip().replace("Z", "+00:00")
    try:
        n = float(s)
        if n > 10_000_000_000:
            n /= 1000.0
        if n > 1_000_000_000:
            return datetime.fromtimestamp(n, tz=timezone.utc).isoformat()
    except Exception:
        pass
    for fmt in (
        "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M",
    ):
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


def backfill_valorant(c):
    import requests
    r = requests.get(VALORANT_RESULTS, headers={"User-Agent": "SevenSportResearchEngine/4.6"}, timeout=45)
    r.raise_for_status()
    raw = r.text
    rows = list(csv.DictReader(io.StringIO(raw)))
    added = 0
    timed = 0
    outcomes = 0
    for row in rows:
        a, b = clean(row.get("team1")), clean(row.get("team2"))
        if not a or not b or a == b:
            continue
        et = iso(row.get("time_completed") or row.get("date") or row.get("completed_at"))
        tournament, stage = clean(row.get("tournament_name")), clean(row.get("round_info"))
        eid = upsert_event(c, "valorant", f"{a} vs {b}", et, "public-vlr-dataset", VALORANT_RESULTS, "COMPLETED", competition=tournament or None, stage=stage or None, season=str(et)[:4] if et else None)
        p1, p2 = upsert_participant(c, "valorant", a, "team"), upsert_participant(c, "valorant", b, "team")
        upsert_ep(c, eid, p1, p1, "A", "match", "public-vlr-dataset", VALORANT_RESULTS)
        upsert_ep(c, eid, p2, p2, "B", "match", "public-vlr-dataset", VALORANT_RESULTS)
        if et:
            timed += 1
        try:
            s1, s2 = float(row.get("score1")), float(row.get("score2"))
        except Exception:
            s1 = s2 = None
        if s1 is not None and s2 is not None:
            side = "A" if s1 > s2 else "B" if s2 > s1 else "DRAW"
            c.execute("""INSERT OR REPLACE INTO event_outcome
                (event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,outcome_status,source,source_url,observed_at_utc,quality_status,reason)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (eid,"valorant",p1,p2,side,s1,s2,"VERIFIED","public-vlr-dataset",VALORANT_RESULTS,utcnow(),"PIT_REQUIRES_REPLAY","Historical label; excluded from pre-event features until PIT replay passes."))
            add_stat(c,eid,p1,p1,"valorant","series.score",s1,str(s1),"public-vlr-dataset",VALORANT_RESULTS)
            add_stat(c,eid,p2,p2,"valorant","series.score",s2,str(s2),"public-vlr-dataset",VALORANT_RESULTS)
            outcomes += 1
        added += 1
    add_snapshot(c,"valorant","public-vlr-dataset",VALORANT_RESULTS,utcnow(),None,hashlib.sha256(raw.encode("utf-8","ignore")).hexdigest(),"UNVERIFIABLE")
    return {"events": added, "timed_events": timed, "verified_outcomes": outcomes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sports", default="valorant")
    a = ap.parse_args()
    sports = [x.strip() for x in a.sports.split(",") if x.strip()]
    c = connect()
    report = {"parser_version":"v4.6.0-dispatch-pit-time", "added":{}, "warnings":[], "timestamp_utc":utcnow()}
    try:
        for sport in sports:
            try:
                if sport == "valorant":
                    report["added"][sport] = backfill_valorant(c)
                elif sport == "rizin":
                    from src.hardened_public_history import backfill_rizin
                    report["added"][sport] = backfill_rizin(c)
                else:
                    report["warnings"].append({"sport":sport,"error":"unsupported dispatcher sport"})
            except Exception as e:
                report["warnings"].append({"sport":sport,"error":repr(e)})
        c.commit()
    finally:
        c.close()
    out = ROOT / "results" / "public_history_backfill.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
