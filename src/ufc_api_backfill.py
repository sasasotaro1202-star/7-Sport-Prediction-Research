from __future__ import annotations
import argparse, csv, hashlib, io, json, re
from datetime import datetime, timezone
import requests
from src.storage.db_v45 import connect, utcnow

BASE='https://ufcapi.aristotle.me'
FALLBACK='https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/data/2026/2026-07-07/ufc_fights.csv'

def sid(*x): return hashlib.sha256('|'.join('' if v is None else str(v) for v in x).encode()).hexdigest()[:32]
def iso(v):
    if not v: return None
    try:
        d=datetime.fromisoformat(str(v).replace('Z','+00:00'))
        if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        for fmt in ('%Y-%m-%d','%B %d, %Y','%b. %d, %Y'):
            try: return datetime.strptime(str(v),fmt).replace(tzinfo=timezone.utc).isoformat()
            except Exception: pass
    return None

def unwrap(x):
    if isinstance(x,list): return x
    if isinstance(x,dict):
        for k in ('data','events','results','items'):
            if isinstance(x.get(k),list): return x[k]
    return []

def add_match_stat(c,eid,pid,name,value,et,source,url):
    try: num=float(value)
    except Exception: return
    c.execute('''INSERT OR REPLACE INTO match_stats
      (stat_id,event_id,participant_id,team_id,sport,observed_at_utc,effective_at_utc,stat_name,value_num,value_text,unit,source,source_url,quality_status,confidence)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
      (sid('ufc-stat',eid,pid,name,num),eid,pid,None,'ufc',utcnow(),et,name,num,str(value),None,source,url,'UNVERIFIABLE',None))

def insert_api(events,c):
    n=0
    for e in events:
        eid=sid('ufc-api',e.get('id') or e.get('slug') or e.get('name'),e.get('date'))
        et=iso(e.get('date') or e.get('event_date') or e.get('datetime')); now=utcnow()
        name=e.get('name') or e.get('event_name') or f"UFC event {e.get('id')}"
        c.execute('''INSERT INTO event(event_id,sport,competition_id,event_time_utc,event_type,status,source_count,quality_status,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET event_time_utc=COALESCE(excluded.event_time_utc,event.event_time_utc),status=excluded.status,updated_at=excluded.updated_at''',
          (eid,'ufc',name,et,'event','SCHEDULED',1,'PRESENT_NOT_PIT_VERIFIED',now,now))
        fights=e.get('fights') or e.get('fight_card') or []
        if isinstance(fights,dict): fights=unwrap(fights)
        for f in fights:
            names=[]
            for key in ('fighter1','fighter2','red','blue','f1','f2'):
                v=f.get(key) if isinstance(f,dict) else None
                if isinstance(v,dict): names.append(v.get('name') or v.get('full_name'))
                elif isinstance(v,str): names.append(v)
            names=[x.strip() for x in names if isinstance(x,str) and x.strip()]
            if len(names)<2: continue
            for side,name2 in zip(('A','B'),names[:2]):
                pid=sid('ufc-api','fighter',name2)
                c.execute('''INSERT INTO participant(participant_id,sport,participant_type,canonical_name,first_seen_at,last_seen_at)
                  VALUES(?,?,?,?,?,?) ON CONFLICT(participant_id) DO UPDATE SET canonical_name=excluded.canonical_name,last_seen_at=excluded.last_seen_at''',
                  (pid,'ufc','fighter',name2,now,now))
                c.execute('''INSERT OR REPLACE INTO event_participant(event_id,participant_id,side,source,source_url,quality_status)
                  VALUES(?,?,?,?,?,?)''',(eid,pid,side,'ufc-api',BASE+'/api/events','UNVERIFIABLE'))
            n+=1
        ph=hashlib.sha256(json.dumps(e,sort_keys=True,default=str).encode()).hexdigest()
        c.execute('''INSERT OR REPLACE INTO source_snapshot(snapshot_id,source,source_url,retrieved_at_utc,event_time_utc,content_hash,parser_version,availability_status,provenance_json)
          VALUES(?,?,?,?,?,?,?,?,?)''',
          (sid('ufc-api',e.get('id')),'ufc-api',f'{BASE}/api/events',now,et,ph,'ufc-api-v3','UNVERIFIABLE',json.dumps({'sport':'ufc','source':'aristotle public UFC API'},ensure_ascii=False)))
    return len(events),n

def insert_fallback(rows,c):
    event_cache={}; now=utcnow(); n=0; stat_names=set()
    for row in rows:
        date=row.get('date') or row.get('event_date'); event_name=(row.get('event_name') or '').strip()
        f1=(row.get('f1_name') or '').strip(); f2=(row.get('f2_name') or '').strip()
        if not event_name or not date or not f1 or not f2: continue
        et=iso(date)
        if not et: continue
        key=(event_name,date); eid=event_cache.get(key) or sid('ufc-tidytuesday',event_name,date); event_cache[key]=eid
        c.execute('''INSERT INTO event(event_id,sport,competition_id,event_time_utc,event_type,status,source_count,quality_status,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET event_time_utc=COALESCE(excluded.event_time_utc,event.event_time_utc),updated_at=excluded.updated_at''',
          (eid,'ufc',event_name,et,'event','COMPLETED',1,'PRESENT_NOT_PIT_VERIFIED',now,now))
        pids=[]
        for side,name,result,prefix in (('A',f1,row.get('f1_result'),'f1_'),('B',f2,row.get('f2_result'),'f2_')):
            pid=sid('ufc-fighter',name); pids.append(pid)
            c.execute('''INSERT INTO participant(participant_id,sport,participant_type,canonical_name,first_seen_at,last_seen_at)
              VALUES(?,?,?,?,?,?) ON CONFLICT(participant_id) DO UPDATE SET canonical_name=excluded.canonical_name,last_seen_at=excluded.last_seen_at''',
              (pid,'ufc','fighter',name,now,now))
            c.execute('''INSERT OR REPLACE INTO event_participant(event_id,participant_id,side,source,source_url,quality_status)
              VALUES(?,?,?,?,?,?)''',(eid,pid,side,'TidyTuesday-2026-07-07',FALLBACK,'UNVERIFIABLE'))
            if result:
                c.execute('''INSERT OR REPLACE INTO participant_history(history_id,participant_id,sport,event_id,observed_at_utc,effective_at_utc,attribute,value_text,source,source_url,quality_status,confidence)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (sid(pid,eid,'result'),pid,'ufc',eid,now,et,'fight_result',result,'TidyTuesday-2026-07-07',FALLBACK,'UNVERIFIABLE',0.9))
            # Fight-level statistics become effective at the fight time, never before it.
            # Therefore PIT replay for this fight cannot see these post-event statistics,
            # while later fights can use them as historical form.
            for key,value in row.items():
                if not key.startswith(prefix) or key in (prefix+'name',prefix+'result'): continue
                try: num=float(value)
                except Exception: continue
                stat=re.sub(r'[^A-Za-z0-9_]+','_',key).strip('_')
                if stat:
                    add_match_stat(c,eid,pid,stat,num,et,'TidyTuesday-2026-07-07',FALLBACK)
                    stat_names.add(stat)
        results=(row.get('f1_result') or '')+'|'+(row.get('f2_result') or '')
        outcome='A' if row.get('f1_result')=='W' else ('B' if row.get('f2_result')=='W' else 'DRAW' if 'D' in results else None)
        if outcome:
            c.execute('''INSERT OR REPLACE INTO event_outcome(event_id,sport,side_a_participant_id,side_b_participant_id,outcome,outcome_status,source,source_url,observed_at_utc,quality_status,reason)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
              (eid,'ufc',pids[0],pids[1],outcome,'VERIFIED','TidyTuesday-2026-07-07',FALLBACK,now,'UNVERIFIABLE','Historical dataset; publication-time provenance not verified'))
        ph=hashlib.sha256(json.dumps(row,sort_keys=True,default=str).encode()).hexdigest()
        c.execute('''INSERT OR REPLACE INTO source_snapshot(snapshot_id,source,source_url,retrieved_at_utc,event_time_utc,content_hash,parser_version,availability_status,provenance_json)
          VALUES(?,?,?,?,?,?,?,?,?)''',
          (sid('TidyTuesday-2026-07-07',event_name,date,f1,f2),'TidyTuesday-2026-07-07',FALLBACK,now,et,ph,'ufc-fallback-v2','UNVERIFIABLE',json.dumps({'sport':'ufc','dataset':'ufc_fights.csv','pit_policy':'post_event_stats_effective_at_event_time'},ensure_ascii=False)))
        n+=1
    return len(event_cache),n,sorted(stat_names)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--limit',type=int,default=100); a=ap.parse_args(); c=connect(); used='api'
    try:
        s=requests.Session(); s.headers['User-Agent']='SevenSportResearchEngine/4.5.15'
        r=s.get(f'{BASE}/api/events',params={'limit':a.limit},timeout=20); r.raise_for_status(); events=unwrap(r.json()); ec,fc=insert_api(events,c); stats=[]
    except Exception as api_error:
        used='tidytuesday-fallback'; r=requests.get(FALLBACK,headers={'User-Agent':'SevenSportResearchEngine/4.5.15'},timeout=45); r.raise_for_status()
        rows=list(csv.DictReader(io.StringIO(r.text))); ec,fc,stats=insert_fallback(rows,c)
        print(json.dumps({'api_error':repr(api_error),'fallback_rows':len(rows)},ensure_ascii=False))
    c.commit(); c.close(); print(json.dumps({'source':used,'events':ec,'fight_cards':fc,'stat_features':stats},ensure_ascii=False))

if __name__=='__main__': main()
