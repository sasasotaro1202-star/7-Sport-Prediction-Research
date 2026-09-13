from __future__ import annotations
import csv, hashlib, io, json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from src.storage.db_v45 import connect, utcnow
from src.seven_sport_production import upsert_event, upsert_participant, upsert_ep, add_stat, add_snapshot
from src.robust_sport_adapters_v2 import HTTP, collect_rizin, collect_volleyball

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
UFC_DATASET='https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/data/2026/2026-07-07/ufc_fights.csv'
VLR_API='https://vlrggapi.vercel.app/v2/match'

def iso(v):
    if not v:return None
    s=str(v).strip().replace('Z','+00:00')
    for fmt in ('%B %d, %Y','%b %d, %Y','%Y-%m-%d'):
        try:return datetime.strptime(s,fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:pass
    try:
        d=datetime.fromisoformat(s)
        if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:return None

def collect_ufc_fixed(c,h):
    raw,r,_,via=h.get(UFC_DATASET)
    rows=list(csv.DictReader(io.StringIO(raw))); groups={}
    for row in rows:
        name=str(row.get('event_name') or '').strip(); date=str(row.get('date') or '').strip()
        if not name or not date:continue
        groups.setdefault((name,date),[]).append(row)
    total=0; stats=0
    for (ename,date),items in groups.items():
        et=iso(date); event_key=f'{UFC_DATASET}#{ename}|{date}'
        eid=upsert_event(c,'ufc',ename,et,'ufcstats-tidytuesday',event_key,'COMPLETED')
        for row in items:
            f1=str(row.get('f1_name') or '').strip();f2=str(row.get('f2_name') or '').strip()
            if not f1 or not f2:continue
            p1=upsert_participant(c,'ufc',f1,'fighter');p2=upsert_participant(c,'ufc',f2,'fighter')
            src=row.get('fight_url') or UFC_DATASET
            upsert_ep(c,eid,p1,p1,'A',None,'ufcstats-tidytuesday',src)
            upsert_ep(c,eid,p2,p2,'B',None,'ufcstats-tidytuesday',src)
            for key,val in row.items():
                if key in {'f1_name','f2_name','event_name','fight_url','date'} or val in ('',None):continue
                try:num=float(val)
                except Exception:num=None
                if num is not None or val:
                    add_stat(c,eid,p1,p1,'ufc',f'A.{key}',num,str(val),'ufcstats-tidytuesday',src);stats+=1
            total+=1
    c.commit()
    # Dataset publication is the historical availability boundary, not retrieval time.
    c.execute("UPDATE source_snapshot SET source_available_at_utc=? WHERE source_url=?",('2026-07-07T00:00:00+00:00',UFC_DATASET))
    add_snapshot(c,'ufc','ufcstats-tidytuesday',UFC_DATASET,r,None,hashlib.sha256(raw.encode()).hexdigest(),'UNVERIFIABLE')
    c.execute("UPDATE source_snapshot SET source_available_at_utc=? WHERE source_url=?",('2026-07-07T00:00:00+00:00',UFC_DATASET));c.commit()
    return total,stats

def collect_vlr_api(c,h,pages=20):
    total=0
    endpoints=[f'{VLR_API}?q=results&num_pages={pages}',f'{VLR_API}?q=upcoming&num_pages=5']
    for url in endpoints:
        raw,r,_,via=h.get(url); data=json.loads(raw)
        segments=((data.get('data') or {}).get('segments') or [])
        if not isinstance(segments,list):continue
        for seg in segments:
            t1=str(seg.get('team1') or '').strip();t2=str(seg.get('team2') or '').strip()
            if not t1 or not t2 or t1.lower()=='tbd' or t2.lower()=='tbd':continue
            match_url=seg.get('match_page') or seg.get('url') or ''
            if match_url and match_url.startswith('/'):match_url=urljoin('https://www.vlr.gg',match_url)
            title=f'{t1} vs {t2}'
            et=None
            ts=seg.get('unix_timestamp') or seg.get('date')
            if ts:
                try:
                    if str(ts).isdigit():et=datetime.fromtimestamp(int(ts),tz=timezone.utc).isoformat()
                    else:et=iso(ts)
                except Exception:pass
            status='COMPLETED' if 'results' in url else 'SCHEDULED'
            eid=upsert_event(c,'valorant',title,et,'vlrggapi',match_url or url,status)
            for i,n in enumerate((t1,t2)):
                pid=upsert_participant(c,'valorant',n,'team');upsert_ep(c,eid,pid,pid,'A' if i==0 else 'B',None,'vlrggapi',match_url or url)
            for key,val in seg.items():
                if key in {'team1','team2','match_page','url'} or val in ('',None):continue
                try:num=float(val)
                except Exception:num=None
                if num is not None:add_stat(c,eid,upsert_participant(c,'valorant',t1,'team'),upsert_participant(c,'valorant',t1,'team'),'valorant',f'feed.{key}',num,str(val),'vlrggapi',match_url or url)
            add_snapshot(c,'valorant','vlrggapi',match_url or url,r,et,hashlib.sha256(raw.encode()).hexdigest(),'UNVERIFIABLE');total+=1
        c.commit()
    return total

def main():
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--sport',choices=['valorant','ufc','rizin','volleyball']);ap.add_argument('--vlr-pages',type=int,default=20);ap.add_argument('--max-pages',type=int,default=40)
    a=ap.parse_args();c=connect();h=HTTP();done={};errors=[]
    jobs=[a.sport] if a.sport else ['valorant','ufc','rizin','volleyball']
    for sp in jobs:
        try:
            if sp=='valorant':done[sp]=collect_vlr_api(c,h,a.vlr_pages)
            elif sp=='ufc':done[sp]=collect_ufc_fixed(c,h)[0]
            elif sp=='rizin':done[sp]=collect_rizin(c,h,a.max_pages)
            else:done[sp]=collect_volleyball(c,h,a.max_pages)
        except Exception as e:errors.append({'sport':sp,'error':repr(e)})
    c.commit();c.close()
    report={'parser_version':'v4.5.10-robust-adapter-v3','done':done,'errors':errors,'timestamp_utc':utcnow()}
    p=ROOT/'results/robust_adapter.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(1 if errors else 0)
if __name__=='__main__':main()
