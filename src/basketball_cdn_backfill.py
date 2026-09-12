from __future__ import annotations
import argparse, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
import requests

from src.storage.db_v45 import connect, utcnow

ROOT = Path(__file__).resolve().parents[1]
SPORT = 'basketball'
UA = 'SevenSportResearchEngine/4.5.11'


def iso(v):
    if not v:
        return None
    s = str(v).replace('Z', '+00:00')
    try:
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def sid(*x):
    return hashlib.sha256('|'.join('' if v is None else str(v) for v in x).encode()).hexdigest()[:32]


def clean(x):
    return re.sub(r'\s+', ' ', str(x or '')).strip()


def ensure(c):
    c.execute('CREATE TABLE IF NOT EXISTS collection_state(state_key TEXT PRIMARY KEY,sport TEXT NOT NULL,scope TEXT NOT NULL,cursor TEXT,completed INTEGER NOT NULL DEFAULT 0,updated_at_utc TEXT NOT NULL,metadata_json TEXT NOT NULL DEFAULT \'{}\')')
    c.commit()


def upsert_event(c, league, game):
    et = iso(game.get('gameTimeUTC') or game.get('gameEt'))
    eid = sid(SPORT, 'nba-cdn', league, game.get('gameId'))
    now = utcnow()
    c.execute('''INSERT INTO event(event_id,sport,competition_id,season,stage,round,event_time_utc,event_type,status,source_count,quality_status,rejection_reason,created_at,updated_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(event_id) DO UPDATE SET event_time_utc=COALESCE(excluded.event_time_utc,event.event_time_utc),status=excluded.status,updated_at=excluded.updated_at''',
              (eid,SPORT,league,None,None,None,et,'match',clean(game.get('gameStatusText') or 'SCHEDULED'),1,'PRESENT_NOT_PIT_VERIFIED',None,now,now))
    return eid


def participant(c, league, team):
    name = clean(' '.join(x for x in (team.get('teamCity'), team.get('teamName')) if x))
    pid = sid(SPORT,league,'team',team.get('teamId'),name)
    now = utcnow()
    c.execute('''INSERT INTO participant(participant_id,sport,participant_type,canonical_name,first_seen_at,last_seen_at)
                 VALUES(?,?,?,?,?,?) ON CONFLICT(participant_id) DO UPDATE SET canonical_name=excluded.canonical_name,last_seen_at=excluded.last_seen_at''',
              (pid,SPORT,'team',name,now,now))
    return pid, name


def collect(league_id, date_label=None):
    c = connect(); ensure(c)
    url = f'https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_{league_id}.json'
    headers = {'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36','Accept':'application/json, text/plain, */*','Accept-Language':'en-US,en;q=0.9','Origin':'https://www.nba.com','Referer':'https://www.nba.com/'}
    r = requests.get(url,headers=headers,timeout=20)
    r.raise_for_status()
    data = r.json(); games = data.get('scoreboard',{}).get('games',[]) or []
    for g in games:
        eid = upsert_event(c,'WNBA' if league_id=='10' else 'NBA',g)
        teams = [g.get('homeTeam') or {}, g.get('awayTeam') or {}]
        for i,t in enumerate(teams):
            pid,name = participant(c,'WNBA' if league_id=='10' else 'NBA',t)
            c.execute('''INSERT OR REPLACE INTO event_participant(event_id,participant_id,team_id,side,role,seed,lineup_status,source,source_url,effective_at_utc,quality_status)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(eid,pid,pid,'A' if i==0 else 'B',None,None,None,'nba-cdn',url,None,'UNVERIFIABLE'))
            for key in ('score','wins','losses','inBonus','timeoutsRemaining'):
                if key not in t: continue
                v=t.get(key); num=None
                try: num=float(v)
                except Exception: pass
                c.execute('''INSERT OR REPLACE INTO match_stats(stat_id,event_id,participant_id,team_id,sport,observed_at_utc,effective_at_utc,stat_name,value_num,value_text,unit,source,source_url,quality_status,confidence)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(sid(eid,pid,key,v),eid,pid,pid,SPORT,utcnow(),None,key,num,str(v),'', 'nba-cdn',url,'UNVERIFIABLE',None))
        ph=hashlib.sha256(json.dumps(g,sort_keys=True).encode()).hexdigest()
        c.execute('''INSERT OR REPLACE INTO source_snapshot(snapshot_id,source,source_url,retrieved_at_utc,source_available_at_utc,event_time_utc,content_hash,payload_path,parser_version,availability_status,provenance_json)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(sid('nba-cdn',url,g.get('gameId')),utcnow(),url,utcnow(),None,iso(g.get('gameTimeUTC')),ph,None,'v4.5.11','UNVERIFIABLE',json.dumps({'sport':SPORT,'league':league_id},ensure_ascii=False)))
    c.commit(); c.close()
    print(json.dumps({'league':league_id,'games':len(games),'source':url},ensure_ascii=False))


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--league',choices=('00','10')); ap.add_argument('--both',action='store_true'); a=ap.parse_args()
    leagues=('00','10') if a.both or not a.league else (a.league,)
    for league in leagues: collect(league)

if __name__=='__main__': main()
