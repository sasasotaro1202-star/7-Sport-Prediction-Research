from __future__ import annotations
import csv, hashlib, io, json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from src.storage.db_v45 import connect, utcnow
from src.seven_sport_production import upsert_event, upsert_participant, upsert_ep, add_stat, add_snapshot
from src.robust_sport_adapters_v2 import HTTP, collect_rizin, collect_volleyball, collect_vlr

ROOT = Path(__file__).resolve().parents[1]
UFC_DATASET = 'https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/data/2026/2026-07-07/ufc_fights.csv'
UFC_PUBLICATION = '2026-07-07T00:00:00+00:00'
VLR_API = 'https://vlrggapi.vercel.app/v2/match'


def iso(v):
    if not v:
        return None
    s=str(v).strip().replace('Z','+00:00')
    for fmt in ('%B %d, %Y','%b %d, %Y','%Y-%m-%d'):
        try: return datetime.strptime(s,fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError: pass
    try:
        d=datetime.fromisoformat(s)
        if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception: return None


def collect_ufc_fight_level(c, h):
    raw, retrieved, _, _ = h.get(UFC_DATASET)
    rows=list(csv.DictReader(io.StringIO(raw)))
    events=fights=stats=0
    for idx,row in enumerate(rows,1):
        card=str(row.get('event_name') or '').strip()
        date=str(row.get('date') or '').strip()
        f1=str(row.get('f1_name') or '').strip()
        f2=str(row.get('f2_name') or '').strip()
        if not card or not date or not f1 or not f2:
            continue
        et=iso(date)
        fight_url=str(row.get('fight_url') or UFC_DATASET)
        # Prediction granularity is one fight, not one UFC card.
        fight_name=f'{card} | {f1} vs {f2}'
        eid=upsert_event(c,'ufc',fight_name,et,'ufcstats-tidytuesday',fight_url,'COMPLETED',competition=card,season=date[:4])
        p1=upsert_participant(c,'ufc',f1,'fighter')
        p2=upsert_participant(c,'ufc',f2,'fighter')
        upsert_ep(c,eid,p1,p1,'A','fight','ufcstats-tidytuesday',fight_url)
        upsert_ep(c,eid,p2,p2,'B','fight','ufcstats-tidytuesday',fight_url)
        r1=str(row.get('f1_result') or '').strip().upper()
        r2=str(row.get('f2_result') or '').strip().upper()
        outcome='A' if r1=='W' else 'B' if r2=='W' else 'DRAW' if r1 in {'D','DRAW'} or r2 in {'D','DRAW'} else None
        if outcome:
            c.execute('''INSERT OR REPLACE INTO event_outcome
                (event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,outcome_status,source,source_url,observed_at_utc,quality_status,reason)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (eid,'ufc',p1,p2,outcome,None,None,'VERIFIED','ufcstats-tidytuesday',UFC_DATASET,utcnow(),'PIT_REQUIRES_REPLAY','Explicit result in dataset'))
        for key,val in row.items():
            if key in {'f1_name','f2_name','event_name','fight_url','date'} or val in ('',None):
                continue
            try: num=float(val)
            except Exception: num=None
            if key.startswith('f1_'): pid,side=p1,'A'
            elif key.startswith('f2_'): pid,side=p2,'B'
            else: pid,side=p1,'META'
            add_stat(c,eid,pid,pid,'ufc',f'fight.{side}.{key}',num,str(val),'ufcstats-tidytuesday',UFC_DATASET)
            stats+=1
        fights+=1
        events+=1
    # One exact publication boundary for the source used by all rows.
    add_snapshot(c,'ufc','ufcstats-tidytuesday',UFC_DATASET,retrieved,None,hashlib.sha256(raw.encode()).hexdigest(),'EXACT')
    c.execute("UPDATE source_snapshot SET source_available_at_utc=?, availability_status='EXACT' WHERE source_url=?",(UFC_PUBLICATION,UFC_DATASET))
    c.commit()
    return {'events':events,'fights':fights,'stats':stats}


def collect_vlr_api(c,h,pages):
    # The hosted vlrggapi is currently known to be unavailable. Keep this route
    # opportunistic and fall back to the direct VLR adapter without treating the
    # API's retrieval time as historical publication time.
    total=0
    for url in (f'{VLR_API}?q=results&num_pages={pages}',f'{VLR_API}?q=upcoming&num_pages=5'):
        try: raw,retrieved,_,_=h.get(url)
        except Exception: continue
        try: data=json.loads(raw)
        except Exception: continue
        segments=((data.get('data') or {}).get('segments') or [])
        for seg in segments if isinstance(segments,list) else []:
            t1=str(seg.get('team1') or '').strip(); t2=str(seg.get('team2') or '').strip()
            if not t1 or not t2 or t1.lower()=='tbd' or t2.lower()=='tbd': continue
            match_url=seg.get('match_page') or seg.get('url') or url
            if match_url.startswith('/'): match_url=urljoin('https://www.vlr.gg',match_url)
            raw_ts=str(seg.get('unix_timestamp') or seg.get('date') or '')
            et=None
            try: et=datetime.fromtimestamp(int(raw_ts),tz=timezone.utc).isoformat()
            except Exception: et=iso(raw_ts)
            eid=upsert_event(c,'valorant',f'{t1} vs {t2}',et,'vlrggapi',match_url,'COMPLETED' if 'results' in url else 'SCHEDULED')
            for i,n in enumerate((t1,t2)):
                pid=upsert_participant(c,'valorant',n,'team'); upsert_ep(c,eid,pid,pid,'A' if i==0 else 'B','match','vlrggapi',match_url)
            add_snapshot(c,'valorant','vlrggapi',match_url,retrieved,et,hashlib.sha256(raw.encode()).hexdigest(),'UNVERIFIABLE')
            total+=1
        c.commit()
    return total


def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('--sport',choices=['valorant','ufc','rizin','volleyball'])
    ap.add_argument('--vlr-pages',type=int,default=20)
    ap.add_argument('--max-pages',type=int,default=40)
    a=ap.parse_args()
    c=connect(); h=HTTP(); done={}; errors=[]
    jobs=[a.sport] if a.sport else ['valorant','ufc','rizin','volleyball']
    for sp in jobs:
        try:
            if sp=='ufc': done[sp]=collect_ufc_fight_level(c,h)
            elif sp=='valorant':
                n=collect_vlr_api(c,h,a.vlr_pages)
                if n: done[sp]={'events':n,'route':'vlrggapi'}
                else: done[sp]={'events':collect_vlr(c,h,a.vlr_pages),'route':'vlr.gg'}
            elif sp=='rizin': done[sp]={'events_or_fights':collect_rizin(c,h,a.max_pages)}
            else: done[sp]={'events':collect_volleyball(c,h,a.max_pages)}
        except Exception as e:
            errors.append({'sport':sp,'error':repr(e)})
    c.commit(); c.close()
    report={'parser_version':'v4.5.11-robust-adapter-v4','done':done,'errors':errors,'timestamp_utc':utcnow()}
    p=ROOT/'results/robust_adapter.json'; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(1 if errors else 0)


if __name__=='__main__': main()
