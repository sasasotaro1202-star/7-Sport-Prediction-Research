from __future__ import annotations
import csv, hashlib, io
from datetime import datetime, timezone
import requests
from src.storage.db_v45 import connect, utcnow
BASES={'atp':'https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_matches_{year}.csv','wta':'https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/wta_matches_{year}.csv'}
def sid(*x): return hashlib.sha256('|'.join('' if v is None else str(v) for v in x).encode()).hexdigest()[:32]
def iso_date(x):
    try: return datetime.strptime(str(x),'%Y%m%d').replace(tzinfo=timezone.utc).isoformat()
    except Exception: return None
def num(x):
    try: return float(x)
    except Exception: return None
def ensure_outcome(c):
    c.execute('''CREATE TABLE IF NOT EXISTS event_outcome(event_id TEXT PRIMARY KEY,sport TEXT NOT NULL,side_a_participant_id TEXT,side_b_participant_id TEXT,outcome TEXT,score_a REAL,score_b REAL,outcome_status TEXT NOT NULL,source TEXT,source_url TEXT,observed_at_utc TEXT NOT NULL,quality_status TEXT NOT NULL,reason TEXT)'''); c.commit()
def ingest_tour(c,tour,year,timeout=30):
    url=BASES[tour].format(year=year); r=requests.get(url,timeout=timeout,headers={'User-Agent':'SevenSportResearchEngine/4.6'})
    if r.status_code!=200: return 0
    rows=list(csv.DictReader(io.StringIO(r.text))); n=0
    for z in rows:
        winner=(z.get('winner_name') or '').strip(); loser=(z.get('loser_name') or '').strip(); dt=iso_date(z.get('tourney_date'))
        if not winner or not loser or not dt: continue
        eid=sid('tennis',tour,z.get('tourney_date'),z.get('tourney_name'),z.get('round'),winner,loser); now=utcnow()
        c.execute('''INSERT INTO event(event_id,sport,competition_id,season,stage,round,event_time_utc,event_type,status,source_count,quality_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET event_time_utc=excluded.event_time_utc,status=excluded.status,updated_at=excluded.updated_at''',(eid,'tennis',z.get('tourney_name'),str(year),None,z.get('round'),dt,'match','COMPLETED',1,'PRESENT_NOT_PIT_VERIFIED',now,now))
        pids=[]
        for side,name in [('A',winner),('B',loser)]:
            pid=sid('tennis',name); c.execute('''INSERT INTO participant(participant_id,sport,participant_type,canonical_name,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?) ON CONFLICT(participant_id) DO UPDATE SET last_seen_at=excluded.last_seen_at,canonical_name=excluded.canonical_name,last_seen_at=excluded.last_seen_at''',(pid,'tennis','player',name,now,now))
            c.execute('''INSERT OR REPLACE INTO event_participant(event_id,participant_id,side,source,source_url,effective_at_utc,quality_status) VALUES(?,?,?,?,?,?,?)''',(eid,pid,side,'JeffSackmann',url,dt,'PRESENT_NOT_PIT_VERIFIED')); pids.append(pid)
        stats={'ace':('w_ace','l_ace'),'double_fault':('w_df','l_df'),'first_serve':('w_1stIn','l_1stIn'),'first_serve_points_won':('w_1stWon','l_1stWon'),'break_points_saved':('w_bpSaved','l_bpSaved'),'break_points_won':('w_bpWon','l_bpWon'),'serve_points_won':('w_SvPtsWon','l_SvPtsWon'),'return_points_won':('w_RvPtsWon','l_RvPtsWon'),'total_points_won':('w_totalPtsWon','l_totalPtsWon')}
        for stat,(wa,la) in stats.items():
            for pid,v in zip(pids,(z.get(wa),z.get(la))):
                if v in (None,''): continue
                c.execute('''INSERT OR REPLACE INTO match_stats(stat_id,event_id,participant_id,sport,observed_at_utc,effective_at_utc,stat_name,value_num,source,source_url,quality_status) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(sid(eid,pid,stat,v),eid,pid,'tennis',now,dt,stat,num(v),'JeffSackmann',url,'PRESENT_NOT_PIT_VERIFIED'))
        c.execute('''INSERT OR REPLACE INTO event_outcome(event_id,sport,side_a_participant_id,side_b_participant_id,outcome,outcome_status,source,source_url,observed_at_utc,quality_status,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(eid,'tennis',pids[0],pids[1],'A','VERIFIED','JeffSackmann',url,now,'SOURCE_BACKED','winner_name/loser_name from historical match row'))
        c.execute('INSERT OR REPLACE INTO source_snapshot(snapshot_id,source,source_url,retrieved_at_utc,event_time_utc,parser_version,availability_status,provenance_json) VALUES(?,?,?,?,?,?,?,?)',(sid('tennis',tour,year,url),'JeffSackmann',url,now,dt,'tennis-bulk-v2','UNVERIFIABLE','{"dataset":"historical ATP/WTA match CSV","license":"CC BY-NC-SA 4.0"}')); n+=1
    c.commit(); return n
def main():
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--start-year',type=int,default=1990); ap.add_argument('--end-year',type=int,default=datetime.now().year); ap.add_argument('--timeout',type=int,default=30); a=ap.parse_args()
    c=connect(); ensure_outcome(c); total=0
    for tour in ('atp','wta'):
        for year in range(a.start_year,a.end_year+1):
            try: total+=ingest_tour(c,tour,year,a.timeout)
            except Exception as e: print(f'{tour} {year}: {e}')
    print({'tennis_rows_ingested':total}); c.close()
if __name__=='__main__': main()
