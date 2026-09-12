from __future__ import annotations
import argparse, hashlib, json, os, re, sqlite3, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

from src.storage.db_v45 import connect, utcnow

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/db/sports_v45.sqlite'
SPORTS = ('valorant','basketball','volleyball','tennis','ufc','rizin','f1')
PARSER = 'v4.5.10'
UA = os.getenv('SPORTS_PIPELINE_USER_AGENT', 'SevenSportResearchEngine/4.5.10')


def iso(v):
    if not v: return None
    s = str(v).strip().replace('Z', '+00:00')
    try:
        d = datetime.fromisoformat(s)
        if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def sid(*x):
    return hashlib.sha256('|'.join('' if v is None else str(v) for v in x).encode()).hexdigest()[:32]


def clean(x): return re.sub(r'\s+', ' ', str(x or '')).strip()


def counts(c, tables=('event','participant','event_participant','match_stats','source_snapshot','pit_replay','collection_state')):
    return {t: c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in tables}


class HTTP:
    def __init__(self):
        self.timeout = float(os.getenv('V45_HTTP_TIMEOUT','15'))
        self.retries = int(os.getenv('V45_HTTP_RETRIES','2'))
        self.delay = float(os.getenv('V45_REQUEST_DELAY','0.05'))
        self.max_workers = max(1, int(os.getenv('V45_HTTP_WORKERS','8')))
        self.cache_dir = ROOT / 'data/raw/http_cache'
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, url):
        return self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + '.json')

    def get(self, url, use_cache=True):
        cp = self._cache_path(url)
        if use_cache and cp.exists():
            try:
                obj = json.loads(cp.read_text(encoding='utf-8'))
                if obj.get('status') == 200 and obj.get('text') is not None:
                    return obj['text'], obj.get('retrieved_at_utc'), obj.get('headers', {})
            except Exception:
                pass
        last = None
        for n in range(self.retries + 1):
            try:
                if self.delay: time.sleep(self.delay)
                r = requests.get(url, headers={'User-Agent':UA,'Accept-Language':'en-US,en;q=0.8,ja;q=0.6'}, timeout=self.timeout)
                r.raise_for_status()
                txt = r.text
                now = utcnow()
                try:
                    cp.write_text(json.dumps({'status':r.status_code,'text':txt,'retrieved_at_utc':now,'headers':dict(r.headers)}, ensure_ascii=False), encoding='utf-8')
                except Exception: pass
                return txt, now, dict(r.headers)
            except Exception as e:
                last = e
                if n < self.retries: time.sleep(min(1.5 * (n + 1), 5))
        raise last

    def text(self, url): return self.get(url)[0]
    def json(self, url): return json.loads(self.text(url))


def ensure_state(c):
    c.execute('''CREATE TABLE IF NOT EXISTS collection_state(
      state_key TEXT PRIMARY KEY, sport TEXT NOT NULL, scope TEXT NOT NULL,
      cursor TEXT, completed INTEGER NOT NULL DEFAULT 0, updated_at_utc TEXT NOT NULL,
      metadata_json TEXT NOT NULL DEFAULT '{}')''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_collection_state_sport ON collection_state(sport,scope)')
    c.commit()


def state(c, sport, scope):
    r = c.execute('SELECT cursor,completed FROM collection_state WHERE state_key=?',(f'{sport}:{scope}',)).fetchone()
    return (r[0] if r else None, bool(r[1]) if r else False)


def save_state(c, sport, scope, cursor=None, completed=False, metadata=None):
    c.execute('''INSERT INTO collection_state(state_key,sport,scope,cursor,completed,updated_at_utc,metadata_json)
                 VALUES(?,?,?,?,?,?,?) ON CONFLICT(state_key) DO UPDATE SET cursor=excluded.cursor,completed=excluded.completed,updated_at_utc=excluded.updated_at_utc,metadata_json=excluded.metadata_json''',
              (f'{sport}:{scope}',sport,scope,cursor,int(completed),utcnow(),json.dumps(metadata or {},ensure_ascii=False)))
    c.commit()


def init_db(c):
    ensure_state(c)
    c.execute('CREATE INDEX IF NOT EXISTS idx_source_snapshot_url ON source_snapshot(source_url)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_event_sport_time ON event(sport,event_time_utc)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_match_stats_event ON match_stats(event_id)')
    c.commit()


def upsert_event(c, sport, name, et, source, url, status='SCHEDULED', competition=None, season=None, stage=None, round_=None):
    eid = sid(sport, source, name, et, url)
    now = utcnow()
    c.execute('''INSERT INTO event(event_id,sport,competition_id,season,stage,round,event_time_utc,event_type,status,source_count,quality_status,rejection_reason,created_at,updated_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(event_id) DO UPDATE SET event_time_utc=COALESCE(excluded.event_time_utc,event.event_time_utc),status=excluded.status,updated_at=excluded.updated_at''',
              (eid,sport,competition,season,stage,round_,et,'match',status,1,'PRESENT_NOT_PIT_VERIFIED',None,now,now))
    return eid


def upsert_participant(c, sport, name, ptype='team'):
    pid = sid(sport, ptype, name)
    now = utcnow()
    c.execute('''INSERT INTO participant(participant_id,sport,participant_type,canonical_name,first_seen_at,last_seen_at)
                 VALUES(?,?,?,?,?,?) ON CONFLICT(participant_id) DO UPDATE SET last_seen_at=excluded.last_seen_at,canonical_name=COALESCE(excluded.canonical_name,participant.canonical_name)''',
              (pid,sport,ptype,name,now,now))
    return pid


def upsert_ep(c, eid, pid, team_id=None, side=None, role=None, source=None, url=None):
    c.execute('''INSERT OR REPLACE INTO event_participant(event_id,participant_id,team_id,side,role,seed,lineup_status,source,source_url,effective_at_utc,quality_status)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
              (eid,pid,team_id,side,role,None,None,source,url,None,'UNVERIFIABLE'))


def add_stat(c, eid, pid, team_id, sport, name, num, text, source, url):
    c.execute('''INSERT OR REPLACE INTO match_stats(stat_id,event_id,participant_id,team_id,sport,observed_at_utc,effective_at_utc,stat_name,value_num,value_text,unit,source,source_url,quality_status,confidence)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (sid(eid,pid,sport,name,num,text,source),eid,pid,team_id,sport,utcnow(),None,name,num,text,None,source,url,'UNVERIFIABLE',None))


def add_snapshot(c, sport, source, url, retrieved, event_time, payload_hash, avail='UNVERIFIABLE', payload_path=None):
    c.execute('''INSERT OR REPLACE INTO source_snapshot(snapshot_id,source,source_url,retrieved_at_utc,source_available_at_utc,event_time_utc,content_hash,payload_path,parser_version,availability_status,provenance_json)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
              (sid(sport,source,url,payload_hash),source,url,retrieved,None,event_time,payload_hash,payload_path,PARSER,avail,json.dumps({'sport':sport,'parser':PARSER},ensure_ascii=False)))


def parse_jsonld(html):
    out=[]; s=BeautifulSoup(html,'lxml')
    for t in s.select('script[type="application/ld+json"]'):
        try:
            x=json.loads(t.string or t.get_text()); out.extend(x if isinstance(x,list) else [x])
        except Exception: pass
    return [x for x in out if isinstance(x,dict)]


def fetch_many(h, urls):
    out={}
    with ThreadPoolExecutor(max_workers=h.max_workers) as ex:
        futs={ex.submit(h.get,u):u for u in urls}
        for f in as_completed(futs):
            u=futs[f]
            try: out[u]=f.result()
            except Exception: out[u]=None
    return out


def collect_espn(c,h,sport,leagues,start_date,end_date):
    d=start_date
    while d<=end_date:
        urls=[f'https://site.api.espn.com/apis/site/v2/sports/{sport}/{lg}/scoreboard?dates={d.strftime("%Y%m%d")}' for lg in leagues]
        for url in urls:
            try: raw,retrieved,_=h.get(url); data=json.loads(raw)
            except Exception: continue
            ph=hashlib.sha256(raw.encode()).hexdigest(); add_snapshot(c,sport,'espn',url,retrieved,None,ph,'UNVERIFIABLE')
            for ev in data.get('events',[]):
                comp=(ev.get('competitions') or [{}])[0]; et=iso(ev.get('date')); name=clean(ev.get('name') or ev.get('shortName') or ev.get('id')); status=clean((ev.get('status') or {}).get('type',{}).get('name','SCHEDULED'))
                eid=upsert_event(c,sport,name,et,'espn',url,status,urlparse(url).path.split('/')[3] if '/' in urlparse(url).path else None)
                for i,t in enumerate((comp.get('competitors') or [])[:2]):
                    tm=t.get('team') or {}; n=clean(tm.get('displayName') or t.get('displayName')); pid=upsert_participant(c,sport,n,'team'); upsert_ep(c,eid,pid,pid,'A' if i==0 else 'B',None,'espn',url)
                    for st in t.get('statistics') or []:
                        k=st.get('name') or st.get('label'); v=st.get('value')
                        try: num=float(v)
                        except Exception: num=None
                        add_stat(c,eid,pid,pid,sport,k,num,str(v) if v is not None else None,'espn',url)
        c.commit(); d+=timedelta(days=1)


def collect_f1(c,h,years):
    base='https://api.jolpi.ca/ergast/f1'
    for season in years:
        try: data=h.json(f'{base}/{season}.json?limit=100'); races=data.get('MRData',{}).get('RaceTable',{}).get('Races',[])
        except Exception: continue
        for race in races:
            et=iso(f"{race.get('date')}T{race.get('time','00:00:00Z')}"); name=clean(race.get('raceName')); rnd=str(race.get('round')); baseurl=f'{base}/{season}/{rnd}/'; eid=upsert_event(c,'f1',name,et,'jolpica',baseurl,'COMPLETED','F1',str(season),None,rnd)
            for ep in ('results','qualifying','pitstops'):
                try: rr=h.json(f'{base}/{season}/{rnd}/{ep}.json?limit=100').get('MRData',{}).get('RaceTable',{}).get('Races',[])
                except Exception: continue
                for race2 in rr:
                    rows=race2.get('Results',[]) if ep=='results' else race2.get('QualifyingResults',[]) if ep=='qualifying' else race2.get('PitStops',[])
                    for z in rows:
                        dr=z.get('Driver') or {}; n=clean(f"{dr.get('givenName','')} {dr.get('familyName','')}"); pid=upsert_participant(c,'f1',n,'driver'); upsert_ep(c,eid,pid,None,None,ep,'jolpica',baseurl)
                        for k,v in z.items():
                            if isinstance(v,(str,int,float)):
                                try: num=float(v)
                                except Exception: num=None
                                add_stat(c,eid,pid,None,'f1',f'{ep}.{k}',num,str(v),'jolpica',baseurl)
            add_snapshot(c,'f1','jolpica',baseurl,utcnow(),et,None,'UNVERIFIABLE')
        c.commit()


def collect_vlr(c,h,pages):
    scope='vlr-pages'; cur,done=state(c,'valorant',scope); start=max(1,int(cur or 1))
    for p in range(start,pages+1):
        url='https://www.vlr.gg/matches/'+(f'?page={p}' if p>1 else '')
        try: html,retrieved,_=h.get(url)
        except Exception: save_state(c,'valorant',scope,str(p),False); continue
        soup=BeautifulSoup(html,'lxml'); links=[]
        for a in soup.select('a[href*="/match/"]'):
            u=urljoin(url,a.get('href'))
            if re.search(r'/match/\d+/',u): links.append(u)
        links=list(dict.fromkeys(links))
        if not links: save_state(c,'valorant',scope,str(p),True); break
        details=fetch_many(h,links)
        for u,res in details.items():
            if not res: continue
            x,det_retrieved,_=res; s=BeautifulSoup(x,'lxml'); title=clean(s.title.get_text() if s.title else u)
            et=None
            for sel in ('.match-header-date-item','.match-header-link-date','.match-header-date'):
                node=s.select_one(sel)
                if node:
                    txt=clean(node.get_text(' ')); m=re.search(r'(\d{1,2}):(\d{2})',txt)
                    if m: break
            for ld in parse_jsonld(x):
                if ld.get('startDate'): et=iso(ld.get('startDate')); break
            status='COMPLETED' if 'completed' in x.lower() else 'SCHEDULED'; eid=upsert_event(c,'valorant',title,et,'vlr.gg',u,status)
            names=[clean(z.get_text(' ')) for z in s.select('.match-header-link-name') if clean(z.get_text(' '))][:2]
            for i,n in enumerate(names):
                pid=upsert_participant(c,'valorant',n,'team'); upsert_ep(c,eid,pid,pid,'A' if i==0 else 'B',None,'vlr.gg',u)
            add_snapshot(c,'valorant','vlr.gg',u,det_retrieved,et,hashlib.sha256(x.encode()).hexdigest(),'UNVERIFIABLE')
        save_state(c,'valorant',scope,str(p+1),p>=pages); c.commit()


def collect_generic(c,h,sport,seeds,max_pages):
    scope='generic-crawl'; cur,done=state(c,sport,scope)
    queue=list(seeds)
    if cur:
        try: queue=json.loads(cur)
        except Exception: pass
    seen=set(); n=0
    while queue and n<max_pages:
        url=queue.pop(0)
        if url in seen: continue
        seen.add(url); n+=1
        try: html,retrieved,_=h.get(url)
        except Exception: save_state(c,sport,scope,json.dumps(queue),False); continue
        soup=BeautifulSoup(html,'lxml')
        for x in parse_jsonld(html):
            typ=str(x.get('@type',''))
            if typ not in ('SportsEvent','Event') or not (x.get('name') or x.get('startDate')): continue
            name=clean(x.get('name')); et=iso(x.get('startDate')); eid=upsert_event(c,sport,name,et,urlparse(url).netloc,url,clean(str(x.get('eventStatus') or 'SCHEDULED')))
            teams=[]
            for key in ('homeTeam','awayTeam','competitor'):
                v=x.get(key); teams.extend(v if isinstance(v,list) else [v] if isinstance(v,dict) else [])
            for i,t in enumerate(teams[:2]):
                nm=clean(t.get('name') if isinstance(t,dict) else t)
                if nm:
                    pid=upsert_participant(c,sport,nm,'team'); upsert_ep(c,eid,pid,pid,'A' if i==0 else 'B',None,urlparse(url).netloc,url)
            add_snapshot(c,sport,urlparse(url).netloc,url,retrieved,et,hashlib.sha256(html.encode()).hexdigest(),'UNVERIFIABLE')
        for a in soup.find_all('a',href=True):
            u=urljoin(url,a['href'])
            if urlparse(u).netloc==urlparse(url).netloc and u not in seen and re.search(r'(match|game|event|competition|fight|bout|大会|試合)',u,re.I): queue.append(u)
        if n % 10 == 0: save_state(c,sport,scope,json.dumps(queue),False); c.commit()
    save_state(c,sport,scope,json.dumps(queue),not queue); c.commit()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--sport',choices=SPORTS)
    ap.add_argument('--days-back',type=int,default=30)
    ap.add_argument('--full-history',action='store_true')
    ap.add_argument('--start-date')
    ap.add_argument('--end-date')
    ap.add_argument('--reset-state',action='store_true')
    a=ap.parse_args(); sports=[a.sport] if a.sport else list(SPORTS)
    c=connect(); init_db(c)
    if a.reset_state:
        for sp in sports: c.execute('DELETE FROM collection_state WHERE sport=?',(sp,))
        c.commit()
    h=HTTP(); today=datetime.now(timezone.utc).date()
    start=datetime.fromisoformat(a.start_date).date() if a.start_date else today-timedelta(days=a.days_back)
    end=datetime.fromisoformat(a.end_date).date() if a.end_date else today
    before=counts(c)
    errors=[]
    for sport in sports:
        try:
            if sport=='basketball': collect_espn(c,h,sport,['nba','wnba','mens-college-basketball'],start,end)
            elif sport=='tennis': collect_espn(c,h,sport,['atp','wta'],start,end)
            elif sport=='f1': collect_f1(c,h,range(datetime.now(timezone.utc).year-10,datetime.now(timezone.utc).year+1))
            elif sport=='valorant': collect_vlr(c,h,int(os.getenv('V45_VLR_PAGES','180' if a.full_history else '20')))
            elif sport=='volleyball': collect_generic(c,h,sport,['https://en.volleyballworld.com/volleyball/competitions','https://en.volleyballworld.com/volleyball/matches'],200 if a.full_history else 40)
            elif sport=='rizin': collect_generic(c,h,sport,['https://jp.rizinff.com/','https://jp.rizinff.com/_tags/大会情報','https://jp.rizinff.com/fighters'],200 if a.full_history else 40)
            elif sport=='ufc': collect_generic(c,h,sport,['http://ufcstats.com/statistics/events/completed?page=all'],200 if a.full_history else 40)
        except Exception as e:
            errors.append({'sport':sport,'error':repr(e)})
            print(json.dumps({'sport':sport,'status':'COLLECT_FAILED','error':repr(e)},ensure_ascii=False),flush=True)
    after=counts(c)
    deltas={k:after[k]-before[k] for k in after}
    # A collector must never report OK merely because its Python process exited normally.
    # OK requires evidence that the run changed the canonical dataset or that a prior
    # completed checkpoint explicitly proves there was nothing new to collect.
    evidence_rows=sum(max(0,deltas[k]) for k in ('event','participant','event_participant','match_stats','source_snapshot'))
    status='FAILED' if errors else ('OK' if evidence_rows>0 else 'NO_DATA')
    out=ROOT/'results/v45'; out.mkdir(parents=True,exist_ok=True)
    report={'sports':sports,'start_date':start.isoformat(),'end_date':end.isoformat(),'full_history':a.full_history,'parser_version':PARSER,'counts_before':before,'counts_after':after,'deltas':deltas,'evidence_rows':evidence_rows,'errors':errors,'timestamp_utc':utcnow(),'status':status}
    (out/'production_run.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    c.close()
    # Exit non-zero only for actual collector exceptions. NO_DATA is intentionally
    # observable by the workflow/quality gate without masking it as a runner crash.
    raise SystemExit(1 if errors else 0)

if __name__=='__main__': main()
