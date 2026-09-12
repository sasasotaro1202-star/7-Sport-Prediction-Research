from __future__ import annotations
import argparse, hashlib, json, re
from datetime import datetime, timezone
import requests
from src.storage.db_v45 import connect, utcnow

SPORT='basketball'

def iso(v):
    if not v: return None
    try:
        d=datetime.fromisoformat(str(v).replace('Z','+00:00'))
        if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception: return None

def sid(*x): return hashlib.sha256('|'.join('' if v is None else str(v) for v in x).encode()).hexdigest()[:32]
def clean(x): return re.sub(r'\s+',' ',str(x or '')).strip()

def collect(league_id):
    c=connect(); url=f'https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_{league_id}.json'
    headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36','Accept':'application/json, text/plain, */*','Accept-Language':'en-US,en;q=0.9','Origin':'https://www.nba.com','Referer':'https://www.nba.com/'}
    r=requests.get(url,headers=headers,timeout=20); r.raise_for_status(); data=r.json(); games=data.get('scoreboard',{}).get('games',[]) or []
    league='WNBA' if league_id=='10' else 'NBA'
    for g in games:
        eid=sid(SPORT,'nba-cdn',league_id,g.get('gameId')); now=utcnow(); et=iso(g.get('gameTimeUTC') or g.get('gameEt'))
        c.execute('''INSERT INTO event(event_id,sport,competition_id,event_time_utc,event_type,status,source_count,quality_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET event_time_utc=COALESCE(excluded.event_time_utc,event.event_time_utc),status=excluded.status,updated_at=excluded.updated_at''',(eid,SPORT,league,et,'match',clean(g.get('gameStatusText') or 'SCHEDULED'),1,'PRESENT_NOT_PIT_VERIFIED',now,now))
        for i,t in enumerate((g.get('homeTeam') or {},g.get('awayTeam') or {})):
            name=clean(' '.join(x for x in (t.get('teamCity'),t.get('teamName')) if x)); pid=sid(SPORT,league,t.get('teamId'),name)
            c.execute('''INSERT INTO participant(participant_id,sport,participant_type,canonical_name,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?) ON CONFLICT(participant_id) DO UPDATE SET canonical_name=excluded.canonical_name,last_seen_at=excluded.last_seen_at''',(pid,SPORT,'team',name,now,now))
            c.execute('''INSERT OR REPLACE INTO event_participant(event_id,participant_id,team_id,side,source,source_url,quality_status) VALUES(?,?,?,?,?,?,?)''',(eid,pid,pid,'A' if i==0 else 'B','nba-cdn',url,'UNVERIFIABLE'))
            for key in ('score','wins','losses'):
                if key not in t: continue
                v=t.get(key)
                try: num=float(v)
                except Exception: num=None
                c.execute('''INSERT OR REPLACE INTO match_stats(stat_id,event_id,participant_id,team_id,sport,observed_at_utc,stat_name,value_num,value_text,source,source_url,quality_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(sid(eid,pid,key,v),eid,pid,pid,SPORT,now,key,num,str(v),'nba-cdn',url,'UNVERIFIABLE'))
        payload=json.dumps(g,sort_keys=True,separators=(',',':')).encode(); ph=hashlib.sha256(payload).hexdigest()
        c.execute('''INSERT OR REPLACE INTO source_snapshot(snapshot_id,source,source_url,retrieved_at_utc,source_available_at_utc,event_time_utc,content_hash,parser_version,availability_status,provenance_json) VALUES(?,?,?,?,?,?,?,?,?,?)''',(sid('nba-cdn',league_id,g.get('gameId')), 'nba-cdn',url,now,None,et,ph,'v4.5.12','UNVERIFIABLE',json.dumps({'sport':SPORT,'league':league},ensure_ascii=False)))
    c.commit(); c.close(); print(json.dumps({'league':league,'games':len(games),'source':url},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--league',choices=('00','10')); ap.add_argument('--both',action='store_true'); a=ap.parse_args(); leagues=('00','10') if a.both or not a.league else (a.league,)
    for x in leagues: collect(x)
if __name__=='__main__': main()
