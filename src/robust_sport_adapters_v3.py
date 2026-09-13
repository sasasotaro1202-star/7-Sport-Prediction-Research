from __future__ import annotations
import csv, hashlib, io, json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from src.storage.db_v45 import connect, utcnow
from src.seven_sport_production import upsert_event, upsert_participant, upsert_ep, add_stat, add_snapshot
from src.robust_sport_adapters_v2 import HTTP, collect_rizin, collect_volleyball, collect_vlr

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
UFC_DATASET = "https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/data/2026/2026-07-07/ufc_fights.csv"
UFC_PUBLICATION = "2026-07-07T00:00:00+00:00"
VLR_API = "https://vlrggapi.vercel.app/v2/match"

def iso(v):
    if not v: return None
    s = str(v).strip().replace("Z", "+00:00")
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try: return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError: pass
    try:
        d = datetime.fromisoformat(s)
        if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception: return None

def _set_exact_source_time(c, url):
    c.execute("UPDATE source_snapshot SET source_available_at_utc=?, availability_status='EXACT' WHERE source_url=?", (UFC_PUBLICATION, url))

def collect_ufc_fixed(c, h):
    raw, retrieved, _, _ = h.get(UFC_DATASET)
    rows = list(csv.DictReader(io.StringIO(raw)))
    groups = {}
    for row in rows:
        name, date = str(row.get("event_name") or "").strip(), str(row.get("date") or "").strip()
        if name and date: groups.setdefault((name, date), []).append(row)
    events = fights = stats = 0
    for (ename, date), items in groups.items():
        et = iso(date)
        # Event identity is the card (event_name + date), never the fight URL.
        event_url = f"{UFC_DATASET}#event|{ename}|{date}"
        eid = upsert_event(c, "ufc", ename, et, "ufcstats-tidytuesday", event_url, "COMPLETED")
        events += 1; winner = None
        for fight_index, row in enumerate(items, 1):
            f1, f2 = str(row.get("f1_name") or "").strip(), str(row.get("f2_name") or "").strip()
            if not f1 or not f2: continue
            p1, p2 = upsert_participant(c, "ufc", f1, "fighter"), upsert_participant(c, "ufc", f2, "fighter")
            fight_url = row.get("fight_url") or UFC_DATASET
            upsert_ep(c, eid, p1, p1, "A", f"fight_{fight_index}", "ufcstats-tidytuesday", fight_url)
            upsert_ep(c, eid, p2, p2, "B", f"fight_{fight_index}", "ufcstats-tidytuesday", fight_url)
            r1, r2 = str(row.get("f1_result") or "").strip().upper(), str(row.get("f2_result") or "").strip().upper()
            if winner is None:
                if r1 == "W": winner = "A"
                elif r2 == "W": winner = "B"
                elif r1 in {"D","DRAW"} or r2 in {"D","DRAW"}: winner = "DRAW"
            for key, val in row.items():
                if key in {"f1_name","f2_name","event_name","fight_url","date"} or val in ("", None): continue
                try: num = float(val)
                except Exception: num = None
                if key.startswith("f1_"): target_pid, prefix = p1, f"fight_{fight_index}.A."
                elif key.startswith("f2_"): target_pid, prefix = p2, f"fight_{fight_index}.B."
                else: target_pid, prefix = p1, f"fight_{fight_index}.meta."
                add_stat(c, eid, target_pid, target_pid, "ufc", prefix + key, num, str(val), "ufcstats-tidytuesday", fight_url); stats += 1
            fights += 1
        if winner in {"A","B","DRAW"}:
            ps = c.execute("SELECT participant_id,side FROM event_participant WHERE event_id=? AND side IN ('A','B') ORDER BY role LIMIT 2", (eid,)).fetchall()
            if len(ps) >= 2:
                c.execute("""INSERT OR REPLACE INTO event_outcome
                    (event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,outcome_status,source,source_url,observed_at_utc,quality_status,reason)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (eid,"ufc",ps[0][0],ps[1][0],winner,None,None,"VERIFIED","ufcstats-tidytuesday",UFC_DATASET,utcnow(),"PIT_REQUIRES_REPLAY","Explicit winner/result in published UFCStats-derived dataset"))
    c.commit()
    add_snapshot(c,"ufc","ufcstats-tidytuesday",UFC_DATASET,retrieved,None,hashlib.sha256(raw.encode()).hexdigest(),"EXACT")
    _set_exact_source_time(c,UFC_DATASET); c.commit()
    return events, fights, stats

def collect_vlr_api(c, h, pages=20):
    total = 0
    for url in (f"{VLR_API}?q=results&num_pages={pages}", f"{VLR_API}?q=upcoming&num_pages=5"):
        raw, retrieved, _, _ = h.get(url)
        try: data = json.loads(raw)
        except json.JSONDecodeError: return 0
        segments = ((data.get("data") or {}).get("segments") or [])
        if not isinstance(segments, list): continue
        for seg in segments:
            t1, t2 = str(seg.get("team1") or "").strip(), str(seg.get("team2") or "").strip()
            if not t1 or not t2 or t1.lower() == "tbd" or t2.lower() == "tbd": continue
            match_url = seg.get("match_page") or seg.get("url") or url
            if match_url.startswith("/"): match_url = urljoin("https://www.vlr.gg", match_url)
            ts = seg.get("unix_timestamp") or seg.get("date")
            try: et = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat() if str(ts).isdigit() else iso(ts)
            except Exception: et = None
            eid = upsert_event(c,"valorant",f"{t1} vs {t2}",et,"vlrggapi",match_url,"COMPLETED" if "results" in url else "SCHEDULED")
            for i,name in enumerate((t1,t2)):
                pid = upsert_participant(c,"valorant",name,"team"); upsert_ep(c,eid,pid,pid,"A" if i==0 else "B",None,"vlrggapi",match_url)
            add_snapshot(c,"valorant","vlrggapi",match_url,retrieved,et,hashlib.sha256(raw.encode()).hexdigest(),"UNVERIFIABLE"); total += 1
        c.commit()
    return total

def collect_vlr_robust(c,h,pages=20):
    try:
        n=collect_vlr_api(c,h,pages)
        if n: return n,"vlrggapi"
    except Exception: pass
    try: return collect_vlr(c,h,pages),"vlr.gg"
    except Exception: return 0,"failed"

def main():
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument("--sport",choices=["valorant","ufc","rizin","volleyball"]); ap.add_argument("--vlr-pages",type=int,default=20); ap.add_argument("--max-pages",type=int,default=40)
    a=ap.parse_args(); c,h=connect(),HTTP(); done={}; errors=[]
    for sp in ([a.sport] if a.sport else ["valorant","ufc","rizin","volleyball"]):
        try:
            if sp=="valorant": n,route=collect_vlr_robust(c,h,a.vlr_pages); done[sp]={"events":n,"route":route}
            elif sp=="ufc": e,f,s=collect_ufc_fixed(c,h); done[sp]={"events":e,"fights":f,"stats":s}
            elif sp=="rizin": done[sp]={"events_or_fights":collect_rizin(c,h,a.max_pages)}
            else: done[sp]={"events":collect_volleyball(c,h,a.max_pages)}
        except Exception as e: errors.append({"sport":sp,"error":repr(e)})
    c.commit(); c.close()
    report={"parser_version":"v4.5.10-robust-adapter-v4","done":done,"errors":errors,"timestamp_utc":utcnow()}
    p=ROOT/"results/robust_adapter.json"; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(report,ensure_ascii=False,indent=2)); raise SystemExit(0)
if __name__=="__main__": main()
