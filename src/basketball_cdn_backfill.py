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
    except Exception:
        for fmt in ('%Y-%m-%dT%H:%M:%S','%Y-%m-%d'):
            try: return datetime.strptime(str(v),fmt).replace(tzinfo=timezone.utc).isoformat()
            except Exception: pass
    return None

def sid(*x): return hashlib.sha256('|'.join('' if v is None else str(v) for v in x).encode()).hexdigest()[:32]
def clean(x): return re.sub(r'\s+',' ',str(x or '')).strip()

def flatten_games(obj):
    out=[]
    def walk(x):
        if isinstance(x,dict):
            if ('gameId' in x or 'gid' in x) and (('homeTeam' in x and 'awayTeam' in x) or ('hTeam' in x and 'vTeam' in x)): out.append(x)
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    walk(obj); seen=set(); uniq=[]
    for g in out:
        k=g.get('gameId') or g.get('gid') or g.get('gameCode')
        if k not in seen: seen.add(k); uniq.append(g)
    return uniq

def normalize_game(g,league):
    if 'homeTeam' in g:
        h=g.get('homeTeam') or {}; a=g.get('awayTeam') or {}; gid=g.get('gameId'); et=g.get('gameTimeUTC') or g.get('gameEt')
        return gid,et,h,a,g.get('gameStatusText') or 'Scheduled'
    h=g.get('hTeam') or {}; a=g.get('vTeam') or {}; gid=g.get('gid') or g.get('gameId'); et=g.get('gdte') or g.get('stt')
    h={'teamId':h.get('tid'),'teamName':h.get('tn') or h.get('tc'),'teamCity':h.get('ta') or h.get('tc'),'score':h.get('s')}
    a={'teamId':a.get('tid'),'teamName':a.get('tn') or a.get('tc'),'teamCity':a.get('ta') or a.get('tc'),'score':a.get('s')}
    return gid,et,h,a,g.get('stt') or g.get('gstat') or 'Scheduled'

def espn_games(sport):
    url=f'https://site.api.espn.com/apis/site/v2/sports/basketball/{sport}/scoreboard'
    r=requests.get(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'},timeout=20); r.raise_for_status()
    out=[]
    for e in r.json().get('events',[]):
        comp=(e.get('competitions') or [{}])[0]; cs=comp.get('competitors') or []
        home=next((x for x in cs if x.get('homeAway')=='home'), cs[0] if cs else {})
        away=next((x for x in cs if x.get('homeAway')=='away'), cs[1] if len(cs)>1 else {})
        def team(c):
            t=c.get('team') or {}
            return {'teamId':t.get('id'),'teamName':t.get('displayName') or t.get('shortDisplayName'),'teamCity':'','score':c.get('score')}
        out.append({'gameId':e.get('id'),'gameTimeUTC':e.get('date'),'homeTeam':team(home),'awayTeam':team(away),'gameStatusText':((e.get('status') or {}).get('type') or {}).get('shortDetail') or 'Scheduled'})
    return url,out

def fetch_games(league_id):
    sport='wnba' if league_id=='10' else 'nba'; headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'}
    urls=[]
    for year in (2026,2025): urls.append(f'https://data.nba.com/data/10s/v2015/json/mobile_teams/{sport}/{year}/league/{league_id}_full_schedule.json')
    for url in urls:
        try:
            r=requests.get(url,headers=headers,timeout=20)
            if r.status_code==200:
                games=flatten_games(r.json())
                if games: return url,games
        except Exception: pass
    try:
        return espn_games(sport)
    except Exception:
        live=f'https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_{league_id}.json'
        try:
            r=requests.get(live,headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36','Accept':'application/json, text/plain, */*','Origin':'https://www.nba.com','Referer':'https://www.nba.com/'},timeout=20)
            if r.status_code==200: return live,r.json().get('scoreboard',{}).get('games',[]) or []
        except Exception: pass
        return 'NO_LIVE_SOURCE',[]

def collect(league_id):
    c=connect(); url,games=fetch_games(league_id); league='WNBA' if league_id=='10' else 'NBA'
    for raw in games:
        gid,et,h,a,status=normalize_game(raw,league); eid=sid(SPORT,'nba',league_id,gid); now=utcnow(); et=iso(et)
        c.execute('''INSERT INTO event(event_id,sport,competition_id,event_time_utc,event_type,status,source_count,quality_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET event_time_utc=COALESCE(excluded.event_time_utc,event.event_time_utc),status=excluded.status,updated_at=excluded.updated_at''',(eid,SPORT,league,et,'match',clean(status),1,'PRESENT_NOT_PIT_VERIFIED',now,now))
        for i,t in enumerate((h,a)):
            name=clean(' '.join(x for x in (t.get('teamCity'),t.get('teamName')) if x)); pid=sid(SPORT,league,t.get('teamId'),name)
            c.execute('''INSERT INTO participant(participant_id,sport,participant_type,canonical_name,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?) ON CONFLICT(participant_id) DO UPDATE SET canonical_name=excluded.canonical_name,last_seen_at=excluded.last_seen_at''',(pid,SPORT,'team',name,now,now))
            c.execute('''INSERT OR REPLACE INTO event_participant(event_id,participant_id,team_id,side,source,source_url,quality_status) VALUES(?,?,?,?,?,?,?)''',(eid,pid,pid,'A' if i==0 else 'B','basketball-feed',url,'UNVERIFIABLE'))
            if t.get('score') not in (None,''):
                try: num=float(t.get('score'))
                except Exception: num=None
                c.execute('''INSERT OR REPLACE INTO match_stats(stat_id,event_id,participant_id,team_id,sport,observed_at_utc,stat_name,value_num,value_text,source,source_url,quality_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(sid(eid,pid,'score',t.get('score')),eid,pid,pid,SPORT,now,'score',num,str(t.get('score')),'basketball-feed',url,'UNVERIFIABLE'))
        ph=hashlib.sha256(json.dumps(raw,sort_keys=True,default=str).encode()).hexdigest(); c.execute('''INSERT OR REPLACE INTO source_snapshot(snapshot_id,source,source_url,retrieved_at_utc,event_time_utc,content_hash,parser_version,availability_status,provenance_json) VALUES(?,?,?,?,?,?,?,?,?)''',(sid('basketball-feed',league_id,gid),'basketball-feed',url,now,et,ph,'basketball-v4.5.14','UNVERIFIABLE',json.dumps({'sport':SPORT,'league':league},ensure_ascii=False)))
    c.commit(); c.close(); print(json.dumps({'league':league,'games':len(games),'source':url},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--league',choices=('00','10')); ap.add_argument('--both',action='store_true'); a=ap.parse_args(); leagues=('00','10') if a.both or not a.league else (a.league,)
    for x in leagues: collect(x)
if __name__=='__main__': main()
