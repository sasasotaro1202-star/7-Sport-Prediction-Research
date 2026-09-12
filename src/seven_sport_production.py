from __future__ import annotations
import argparse, hashlib, json, os, re, sqlite3, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1')
UA=os.getenv('SPORTS_PIPELINE_USER_AGENT','SevenSportResearchEngine/4.5.8')

def utc(): return datetime.now(timezone.utc).isoformat()
def iso(v):
    if not v: return None
    s=str(v).strip().replace('Z','+00:00')
    try:
        d=datetime.fromisoformat(s)
        if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return None
def sid(*x): return hashlib.sha256('|'.join('' if v is None else str(v) for v in x).encode()).hexdigest()[:32]
def clean(x): return re.sub(r'\s+',' ',str(x or '')).strip()

class HTTP:
    def __init__(self):
        self.s=requests.Session(); self.s.headers.update({'User-Agent':UA,'Accept-Language':'en-US,en;q=0.8,ja;q=0.6'})
        self.timeout=float(os.getenv('V45_HTTP_TIMEOUT','20')); self.retries=int(os.getenv('V45_HTTP_RETRIES','2')); self.delay=float(os.getenv('V45_REQUEST_DELAY','0.2'))
    def get(self,url):
        last=None
        for n in range(self.retries+1):
            try:
                if self.delay: time.sleep(self.delay)
                r=self.s.get(url,timeout=self.timeout); r.raise_for_status(); return r
            except Exception as e:
                last=e
                if n<self.retries: time.sleep(min(2*(n+1),5))
        raise last
    def text(self,url): return self.get(url).text
    def json(self,url): return self.get(url).json()

def init_db():
    DB.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB)
    c.executescript('''CREATE TABLE IF NOT EXISTS event(event_id TEXT PRIMARY KEY,sport TEXT,competition_id TEXT,season TEXT,stage TEXT,round TEXT,event_time_utc TEXT,event_type TEXT,status TEXT,event_name TEXT,source TEXT,source_url TEXT,quality_status TEXT,rejection_reason TEXT,created_at TEXT,updated_at TEXT);
    CREATE TABLE IF NOT EXISTS participant(participant_id TEXT PRIMARY KEY,sport TEXT,participant_type TEXT,canonical_name TEXT,first_seen_at TEXT,last_seen_at TEXT);
    CREATE TABLE IF NOT EXISTS event_participant(event_id TEXT,participant_id TEXT,team_id TEXT,side TEXT,source TEXT,source_url TEXT,effective_at_utc TEXT,quality_status TEXT,PRIMARY KEY(event_id,participant_id,side));
    CREATE TABLE IF NOT EXISTS match_stats(stat_id TEXT PRIMARY KEY,event_id TEXT,participant_id TEXT,team_id TEXT,sport TEXT,stat_name TEXT,value_num REAL,value_text TEXT,observed_at_utc TEXT,effective_at_utc TEXT,source TEXT,source_url TEXT,quality_status TEXT);
    CREATE TABLE IF NOT EXISTS source_snapshot(snapshot_id TEXT PRIMARY KEY,sport TEXT,source TEXT,source_url TEXT,retrieved_at_utc TEXT,source_available_at_utc TEXT,event_time_utc TEXT,content_hash TEXT,parser_version TEXT,availability_status TEXT,provenance_json TEXT);
    CREATE TABLE IF NOT EXISTS pit_replay(replay_id TEXT PRIMARY KEY,event_id TEXT,prediction_cutoff_at_utc TEXT,cutoff_rule TEXT,replay_status TEXT,leakage_status TEXT,created_at_utc TEXT,reason TEXT);''')
    return c

def save(c,events,participants,eps,stats,sources):
    for r in events:
        c.execute('INSERT OR REPLACE INTO event VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',r)
    for r in participants:
        c.execute('INSERT OR REPLACE INTO participant VALUES (?,?,?,?,?,?)',r)
    for r in eps:
        c.execute('INSERT OR REPLACE INTO event_participant VALUES (?,?,?,?,?,?,?,?)',r)
    for r in stats:
        c.execute('INSERT OR REPLACE INTO match_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',r)
    for r in sources:
        c.execute('INSERT OR REPLACE INTO source_snapshot VALUES (?,?,?,?,?,?,?,?,?,?,?)',r)
    c.commit()

def jsonld(html):
    out=[]; s=BeautifulSoup(html,'lxml')
    for t in s.select('script[type="application/ld+json"]'):
        try:
            x=json.loads(t.string or t.get_text()); out.extend(x if isinstance(x,list) else [x])
        except Exception: pass
    return [x for x in out if isinstance(x,dict)]

def add_event(E,sport,name,et,source,url,status='SCHEDULED',competition=None,season=None,stage=None,round_=None):
    eid=sid(sport,source,name,et,url)
    E.append((eid,sport,competition,season,stage,round_,et,'match',status,name,source,url,'PRESENT_NOT_PIT_VERIFIED',None,utc(),utc()))
    return eid

def collect_espn(h,sport,leagues,days_back,E,P,EP,S):
    end=datetime.now(timezone.utc).date(); start=end-timedelta(days=days_back)
    d=start
    while d<=end:
        day=d.strftime('%Y%m%d')
        for league in leagues:
            url=f'https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={day}'
            try: data=h.json(url)
            except Exception as e:
                continue
            payload=json.dumps(data,sort_keys=True); S.append((sid(sport,url,payload),'espn',sport,url,utc(),None,None,hashlib.sha256(payload.encode()).hexdigest(),'v4.5.8','UNVERIFIABLE','{}'))
            for ev in data.get('events',[]):
                comp=(ev.get('competitions') or [{}])[0]; teams=comp.get('competitors') or []; et=iso(ev.get('date')); name=clean(ev.get('name') or ev.get('shortName') or ev.get('id'))
                status=str(ev.get('status',{}).get('type',{}).get('name','SCHEDULED')); eid=add_event(E,sport,name,et,'espn',url,status,league)
                for i,t in enumerate(teams[:2]):
                    n=clean((t.get('team') or {}).get('displayName') or t.get('displayName')); pid=sid(sport,n); side='A' if i==0 else 'B'
                    P.append((pid,sport,'team',n,utc(),utc())); EP.append((eid,pid,pid,side,'espn',url,None,'UNVERIFIABLE'))
                    for k,v in (t.get('statistics') or []):
                        try: num=float(v)
                        except Exception: num=None
                        stats_id=sid(eid,pid,k,v); S_stat=(stats_id,eid,pid,pid,sport,k,num,None,utc(),None,'espn',url,'UNVERIFIABLE');
                        globals().setdefault('_STATS',[]).append(S_stat)
        d+=timedelta(days=1)

def collect_f1(h,E,P,EP,S,days_back):
    base='https://api.jolpi.ca/ergast/f1'; year=datetime.now(timezone.utc).year
    for season in range(max(1950,year-10),year+1):
        try: races=h.json(f'{base}/{season}.json?limit=100').get('MRData',{}).get('RaceTable',{}).get('Races',[])
        except Exception: continue
        for race in races:
            et=iso(f"{race.get('date')}T{race.get('time','00:00:00Z')}"); name=race.get('raceName'); url=f"{base}/{season}/{race.get('round')}/"; eid=add_event(E,'f1',name,et,'jolpica',url,'SCHEDULED', 'F1',str(season),None,str(race.get('round')))
            for ep in ('results','qualifying','pitstops'):
                try: data=h.json(f"{base}/{season}/{race.get('round')}/{ep}.json?limit=100").get('MRData',{}).get('RaceTable',{}).get('Races',[])
                except Exception: continue
                for rr in data:
                    rows=rr.get('Results',[]) if ep=='results' else rr.get('QualifyingResults',[]) if ep=='qualifying' else rr.get('PitStops',[])
                    for z in rows:
                        dr=z.get('Driver') or {}; n=clean(f"{dr.get('givenName','')} {dr.get('familyName','')}"); pid=sid('f1',dr.get('driverId') or n); P.append((pid,'f1','driver',n,utc(),utc())); EP.append((eid,pid,None,None,'jolpica',url,None,'UNVERIFIABLE'))
                        for k,v in z.items():
                            if isinstance(v,(str,int,float)):
                                try: num=float(v)
                                except Exception: num=None
                                _STATS.append((sid(eid,pid,ep,k,v),eid,pid,None,'f1',f'{ep}.{k}',num,None,utc(),None,'jolpica',url,'UNVERIFIABLE'))
            S.append((sid('f1',url),'jolpica','f1',url,utc(),None,et,None,'v4.5.8','UNVERIFIABLE','{}'))

def collect_vlr(h,E,P,EP,S,full):
    pages=int(os.getenv('V45_VLR_PAGES','30' if not full else '250')); seen=set()
    for p in range(1,pages+1):
        url='https://www.vlr.gg/matches/'+(f'?page={p}' if p>1 else '')
        try: html=h.text(url)
        except Exception: continue
        soup=BeautifulSoup(html,'lxml'); links=[]
        for a in soup.select('a[href*="/match/"]'):
            u=urljoin(url,a.get('href'))
            if re.search(r'/match/\d+/',u): links.append(u)
        links=list(dict.fromkeys(links));
        if not links: break
        for u in links:
            if u in seen: continue
            seen.add(u)
            try: x=h.text(u)
            except Exception: continue
            s=BeautifulSoup(x,'lxml'); names=[clean(z.get_text(' ')) for z in s.select('.match-header-link-name') if clean(z.get_text(' '))][:2]; title=clean(s.title.get_text() if s.title else u); eid=add_event(E,'valorant',title,None,'vlr.gg',u,'COMPLETED' if 'completed' in x.lower() else 'SCHEDULED')
            for i,n in enumerate(names):
                pid=sid('valorant',n); P.append((pid,'valorant','team',n,utc(),utc())); EP.append((eid,pid,pid,'A' if i==0 else 'B','vlr.gg',u,None,'UNVERIFIABLE'))
            S.append((sid('valorant',u), 'vlr.gg','valorant',u,utc(),None,None,hashlib.sha256(x.encode()).hexdigest(),'v4.5.8','UNVERIFIABLE','{}'))

def collect_generic(h,sport,seeds,E,P,EP,S,max_pages=100):
    q=list(seeds); seen=set(); n=0
    while q and n<max_pages:
        url=q.pop(0)
        if url in seen: continue
        seen.add(url); n+=1
        try: html=h.text(url)
        except Exception: continue
        soup=BeautifulSoup(html,'lxml')
        for x in jsonld(html):
            typ=str(x.get('@type',''))
            if typ not in ('SportsEvent','Event') or not (x.get('name') or x.get('startDate')): continue
            name=clean(x.get('name')); et=iso(x.get('startDate')); eid=add_event(E,sport,name,et,urlparse(url).netloc,url,str(x.get('eventStatus') or 'SCHEDULED'))
            teams=[]
            for key in ('homeTeam','awayTeam','competitor'):
                v=x.get(key); teams.extend(v if isinstance(v,list) else [v] if isinstance(v,dict) else [])
            for i,t in enumerate(teams[:2]):
                nm=clean(t.get('name') if isinstance(t,dict) else t); pid=sid(sport,nm); P.append((pid,sport,'team',nm,utc(),utc())); EP.append((eid,pid,pid,'A' if i==0 else 'B',urlparse(url).netloc,url,None,'UNVERIFIABLE'))
            S.append((sid(sport,url,name),'html',sport,url,utc(),None,et,hashlib.sha256(html.encode()).hexdigest(),'v4.5.8','UNVERIFIABLE','{}'))
        for a in soup.find_all('a',href=True):
            u=urljoin(url,a['href'])
            if urlparse(u).netloc==urlparse(url).netloc and u not in seen and re.search(r'(match|game|event|competition|fight|bout|大会|試合)',u,re.I): q.append(u)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--sport',choices=SPORTS); ap.add_argument('--days-back',type=int,default=30); ap.add_argument('--full-history',action='store_true'); a=ap.parse_args(); sports=[a.sport] if a.sport else list(SPORTS)
    c=init_db(); h=HTTP(); E=[];P=[];EP=[];S=[]; global _STATS; _STATS=[]
    for sport in sports:
        if sport=='basketball': collect_espn(h,'basketball',['nba','wnba','mens-college-basketball'],a.days_back,E,P,EP,S)
        elif sport=='tennis': collect_espn(h,'tennis',['atp','wta'],a.days_back,E,P,EP,S)
        elif sport=='f1': collect_f1(h,E,P,EP,S,a.days_back)
        elif sport=='valorant': collect_vlr(h,E,P,EP,S,a.full_history)
        elif sport=='volleyball': collect_generic(h,sport,['https://en.volleyballworld.com/volleyball/competitions','https://en.volleyballworld.com/volleyball/matches'],E,P,EP,S,200 if a.full_history else 40)
        elif sport=='rizin': collect_generic(h,sport,['https://jp.rizinff.com/','https://jp.rizinff.com/_tags/大会情報','https://jp.rizinff.com/fighters'],E,P,EP,S,200 if a.full_history else 40)
        elif sport=='ufc': collect_generic(h,sport,['http://ufcstats.com/statistics/events/completed?page=all'],E,P,EP,S,200 if a.full_history else 40)
    save(c,E,P,EP,_STATS,S); c.close()
    report={'sports':sports,'events':len(E),'participants':len(P),'event_participants':len(EP),'stats':len(_STATS),'sources':len(S),'timestamp_utc':utc(),'status':'OK'}
    out=ROOT/'results/v45'; out.mkdir(parents=True,exist_ok=True); (out/'production_run.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
