from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
import requests
from src.storage.db_v45 import connect, utcnow
BASE='https://api.openf1.org/v1'

def sid(*x): return hashlib.sha256('|'.join('' if v is None else str(v) for v in x).encode()).hexdigest()[:32]

def get(path,params=None,timeout=45,retries=2):
    last=None
    for i in range(retries+1):
        try:
            r=requests.get(BASE+path,params=params or {},timeout=timeout,headers={'User-Agent':'SevenSportResearchEngine/4.6'})
            r.raise_for_status(); return r.json(),r.url
        except Exception as e:
            last=e
            if i<retries: continue
    raise last

def num(x):
    try:return float(x)
    except:return None

def main():
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--start-year',type=int,default=2023); ap.add_argument('--end-year',type=int,default=datetime.now().year); ap.add_argument('--timeout',type=int,default=45); a=ap.parse_args()
    c=connect(); total=0; skipped=0; failed=[]
    for year in range(a.start_year,a.end_year+1):
        try:sessions,url=get('/sessions',{'year':year},a.timeout)
        except Exception as e: failed.append({'year':year,'stage':'sessions','error':repr(e)}); continue
        for s in sessions:
            if str(s.get('session_name','')).lower()!='race': continue
            sk=s.get('session_key'); start=s.get('date_start'); eid=sid('f1-openf1',year,s.get('meeting_key'),sk)
            existing=c.execute("SELECT COUNT(*) FROM match_stats WHERE event_id=? AND source='OpenF1'",(eid,)).fetchone()[0]
            if existing>0:
                skipped+=1; continue
            name=f"{s.get('country_name','')} {year} Race"; now=utcnow()
            c.execute('''INSERT INTO event(event_id,sport,competition_id,season,stage,round,event_time_utc,event_type,status,source_count,quality_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET event_time_utc=COALESCE(excluded.event_time_utc,event.event_time_utc),status=excluded.status,updated_at=excluded.updated_at''',(eid,'f1',str(s.get('meeting_key')),str(year),'race',str(s.get('session_key')),start,'race','COMPLETED',1,'PRESENT_NOT_PIT_VERIFIED',now,now))
            try: results,rurl=get('/session_result',{'session_key':sk},a.timeout)
            except Exception as e: failed.append({'year':year,'session_key':sk,'stage':'session_result','error':repr(e)}); continue
            for z in results:
                dn=z.get('driver_number'); pid=sid('f1-driver',dn)
                c.execute('''INSERT INTO participant(participant_id,sport,participant_type,canonical_name,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?) ON CONFLICT(participant_id) DO UPDATE SET last_seen_at=excluded.last_seen_at''',(pid,'f1','driver',str(dn),now,now))
                c.execute('''INSERT OR REPLACE INTO event_participant(event_id,participant_id,side,role,source,source_url,effective_at_utc,quality_status) VALUES(?,?,?,?,?,?,?,?)''',(eid,pid,'A','driver','OpenF1',rurl,start,'PRESENT_NOT_PIT_VERIFIED'))
                for k,v in z.items():
                    if k in ('driver_number','session_key','meeting_key'): continue
                    if isinstance(v,(int,float)):
                        c.execute('''INSERT OR REPLACE INTO match_stats(stat_id,event_id,participant_id,sport,observed_at_utc,effective_at_utc,stat_name,value_num,source,source_url,quality_status) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(sid(eid,pid,k,v),eid,pid,'f1',now,start,'openf1.'+k,num(v),'OpenF1',rurl,'PRESENT_NOT_PIT_VERIFIED'))
                total+=1
            c.execute('INSERT OR REPLACE INTO source_snapshot(snapshot_id,source,source_url,retrieved_at_utc,source_available_at_utc,event_time_utc,parser_version,availability_status,provenance_json) VALUES(?,?,?,?,?,?,?,?,?)',(sid('openf1',sk), 'OpenF1',rurl,now,None,start,'openf1-v2','UNVERIFIABLE',json.dumps({'year':year,'session_key':sk})))
        c.commit()
    report={'f1_openf1_driver_session_rows':total,'sessions_skipped_already_loaded':skipped,'failed_requests':failed,'status':'OK' if not failed else 'PARTIAL'}
    print(json.dumps(report,ensure_ascii=False)); c.close()
    if failed and total==0 and skipped==0: raise SystemExit(2)
if __name__=='__main__': main()
