from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
import requests
from src.storage.db_v45 import connect, utcnow

BASE='https://ufcapi.aristotle.me'

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

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--limit',type=int,default=100); a=ap.parse_args()
    s=requests.Session(); s.headers['User-Agent']='SevenSportResearchEngine/4.5.13'
    r=s.get(f'{BASE}/api/events',params={'limit':a.limit},timeout=20); r.raise_for_status(); payload=r.json(); events=unwrap(payload)
    c=connect(); n=0
    for e in events:
        eid=sid('ufc-api',e.get('id') or e.get('slug') or e.get('name'),e.get('date'))
        et=iso(e.get('date') or e.get('event_date') or e.get('datetime')); now=utcnow()
        name=e.get('name') or e.get('event_name') or f"UFC event {e.get('id')}"
        c.execute('''INSERT INTO event(event_id,sport,competition_id,event_time_utc,event_type,status,source_count,quality_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET event_time_utc=COALESCE(excluded.event_time_utc,event.event_time_utc),status=excluded.status,updated_at=excluded.updated_at''',(eid,'ufc',name,et,'event','SCHEDULED',1,'PRESENT_NOT_PIT_VERIFIED',now,now))
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
            pids=[]
            for side,name2 in zip(('A','B'),names[:2]):
                pid=sid('ufc-api','fighter',name2); pids.append(pid)
                c.execute('''INSERT INTO participant(participant_id,sport,participant_type,canonical_name,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?) ON CONFLICT(participant_id) DO UPDATE SET canonical_name=excluded.canonical_name,last_seen_at=excluded.last_seen_at''',(pid,'ufc','fighter',name2,now,now))
                c.execute('''INSERT OR REPLACE INTO event_participant(event_id,participant_id,side,source,source_url,quality_status) VALUES(?,?,?,?,?,?)''',(eid,pid,side,'ufc-api',BASE+'/api/events','UNVERIFIABLE'))
            n+=1
        ph=hashlib.sha256(json.dumps(e,sort_keys=True,default=str).encode()).hexdigest()
        c.execute('''INSERT OR REPLACE INTO source_snapshot(snapshot_id,source,source_url,retrieved_at_utc,event_time_utc,content_hash,parser_version,availability_status,provenance_json) VALUES(?,?,?,?,?,?,?,?,?)''',(sid('ufc-api',e.get('id')), 'ufc-api',f'{BASE}/api/events',now,et,ph,'ufc-api-v1','UNVERIFIABLE',json.dumps({'sport':'ufc','source':'aristotle public UFC API'},ensure_ascii=False)))
    c.commit(); c.close(); print(json.dumps({'events':len(events),'fight_cards':n},ensure_ascii=False))
if __name__=='__main__': main()
