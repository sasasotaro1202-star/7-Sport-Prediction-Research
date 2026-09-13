from __future__ import annotations
import hashlib, json, os, re, sqlite3, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

from src.storage.db_v45 import connect, utcnow
from src.seven_sport_production import upsert_event, upsert_participant, upsert_ep, add_stat, add_snapshot

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/db/sports_v45.sqlite'
UA = os.getenv('SPORTS_PIPELINE_USER_AGENT', 'SevenSportResearchEngine/4.5.10-robust-adapter')

class HTTP:
    def __init__(self):
        self.timeout=float(os.getenv('V45_HTTP_TIMEOUT','20'))
        self.retries=int(os.getenv('V45_HTTP_RETRIES','3'))
        self.delay=float(os.getenv('V45_REQUEST_DELAY','0.08'))
        self.workers=max(2,int(os.getenv('V45_HTTP_WORKERS','12')))
        self.cache=ROOT/'data/raw/http_cache'
        self.cache.mkdir(parents=True,exist_ok=True)
    def get(self,url,use_cache=True):
        p=self.cache/(hashlib.sha256(url.encode()).hexdigest()+'.json')
        if use_cache and p.exists():
            try:
                x=json.loads(p.read_text(encoding='utf-8'))
                if x.get('status')==200 and x.get('text') is not None:
                    return x['text'],x.get('retrieved_at_utc'),x.get('headers',{})
            except Exception: pass
        last=None
        for i in range(self.retries+1):
            try:
                if self.delay: time.sleep(self.delay)
                r=requests.get(url,headers={'User-Agent':UA,'Accept-Language':'en-US,en;q=0.8,ja;q=0.7'},timeout=self.timeout)
                r.raise_for_status(); txt=r.text; now=utcnow()
                try: p.write_text(json.dumps({'status':r.status_code,'text':txt,'retrieved_at_utc':now,'headers':dict(r.headers)},ensure_ascii=False),encoding='utf-8')
                except Exception: pass
                return txt,now,dict(r.headers)
            except Exception as e:
                last=e
                if i<self.retries: time.sleep(min(2*(i+1),6))
        raise last

def iso(v):
    if not v:return None
    s=str(v).strip().replace('Z','+00:00')
    try:
        d=datetime.fromisoformat(s)
        if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:return None

def clean(x):return re.sub(r'\s+',' ',str(x or '')).strip()

def jsonld(html):
    out=[];s=BeautifulSoup(html,'lxml')
    for t in s.select('script[type="application/ld+json"]'):
        try:
            z=json.loads(t.string or t.get_text());out.extend(z if isinstance(z,list) else [z])
        except Exception:pass
    return [z for z in out if isinstance(z,dict)]

def many(h,urls):
    out={}
    with ThreadPoolExecutor(max_workers=h.workers) as ex:
        fs={ex.submit(h.get,u):u for u in urls}
        for f in as_completed(fs):
            u=fs[f]
            try:out[u]=f.result()
            except Exception:out[u]=None
    return out

def extract_names(text):
    text=clean(text)
    # Preserve non-Latin names and avoid treating generic labels as fighters/teams.
    parts=re.split(r'\s+vs\.?\s+|\s+VS\s+|\s+対\s+|\s+vs\s+',text)
    if len(parts)==2 and all(len(x)>=2 for x in parts):
        return [clean(parts[0]),clean(parts[1])]
    return []

def collect_vlr(c,h,pages=180):
    # Dedicated VLR adapter. The old collector used /match/\\d+/ and therefore never matched numeric IDs.
    base='https://www.vlr.gg/matches/'
    total=0
    for page in range(1,pages+1):
        url=base+(f'?page={page}' if page>1 else '')
        try:html,retrieved,_=h.get(url)
        except Exception:continue
        soup=BeautifulSoup(html,'lxml')
        links=[]
        for a in soup.select('a[href*="/match/"]'):
            u=urljoin(url,a.get('href',''))
            if re.search(r'/match/\d+(?:/|$)',u):links.append(u)
        links=list(dict.fromkeys(links))
        if not links:break
        for u,res in many(h,links).items():
            if not res:continue
            x,r,_=res;s=BeautifulSoup(x,'lxml')
            title=clean(s.title.get_text(' ')) if s.title else u
            et=None
            for z in jsonld(x):
                if z.get('startDate'):et=iso(z['startDate']);break
            names=[]
            for sel in ('.match-header-link-name','.match-header-vs-note-item'):
                for node in s.select(sel):
                    n=clean(node.get_text(' '))
                    if n and n not in names:names.append(n)
            names=names[:2]
            eid=upsert_event(c,'valorant',title,et,'vlr.gg',u,'COMPLETED' if 'completed' in x.lower() else 'SCHEDULED')
            for i,n in enumerate(names):
                pid=upsert_participant(c,'valorant',n,'team');upsert_ep(c,eid,pid,pid,'A' if i==0 else 'B',None,'vlr.gg',u)
            add_snapshot(c,'valorant','vlr.gg',u,r,et,hashlib.sha256(x.encode()).hexdigest(),'UNVERIFIABLE')
            total+=1
        c.commit()
    return total

def collect_ufc(c,h):
    root='http://ufcstats.com/statistics/events/completed?page=all'
    html,retrieved,_=h.get(root);s=BeautifulSoup(html,'lxml')
    event_urls=[]
    for a in s.select('a[href*="/event-details/"]'):
        u=urljoin(root,a.get('href',''));event_urls.append(u)
    event_urls=list(dict.fromkeys(event_urls))
    # Upcoming events are included for future prediction readiness.
    for u in ('http://ufcstats.com/statistics/events/upcoming?page=all',):
        try:
            x,_,_=h.get(u);ss=BeautifulSoup(x,'lxml')
            event_urls += [urljoin(u,a.get('href','')) for a in ss.select('a[href*="/event-details/"]')]
        except Exception:pass
    event_urls=list(dict.fromkeys(event_urls)); total=0
    for u,res in many(h,event_urls).items():
        if not res:continue
        x,r,_=res;ss=BeautifulSoup(x,'lxml')
        name=clean((ss.select_one('.b-content__title') or ss.title).get_text(' ') if (ss.select_one('.b-content__title') or ss.title) else u)
        date=None
        for node in ss.select('.b-list__box-list-item'):
            txt=clean(node.get_text(' '))
            if 'Date:' in txt:
                date=iso(txt.split('Date:',1)[1]);break
        eid=upsert_event(c,'ufc',name,date,'ufcstats',u,'COMPLETED' if 'completed' in u else 'SCHEDULED')
        rows=ss.select('tr.b-fight-details__table-row.b-fight-details__table-row__hover') or ss.select('tr.b-fight-details__table-row')
        for row in rows:
            names=[]
            for node in row.select('.b-fight-details__table-col.l-page_align_left p.b-fight-details__table-text'):
                n=clean(node.get_text(' '))
                if n and n not in names:names.append(n)
            if len(names)<2:
                texts=[clean(z.get_text(' ')) for z in row.select('.b-fight-details__table-col')]
                for t in texts:
                    nn=extract_names(t)
                    if len(nn)==2:names=nn;break
            names=names[:2]
            if len(names)!=2:continue
            for i,n in enumerate(names):
                pid=upsert_participant(c,'ufc',n,'fighter');upsert_ep(c,eid,pid,pid,'A' if i==0 else 'B',None,'ufcstats',u)
            fight_a=row.get('data-link') or row.get('data-href')
            if fight_a:
                fu=urljoin(u,fight_a)
                try:
                    fx,fr,_=h.get(fu)
                    for z in BeautifulSoup(fx,'lxml').select('.b-fight-details__text-item'):
                        txt=clean(z.get_text(' '));m=re.match(r'([^:]+):\s*(.*)',txt)
                        if m:add_stat(c,eid,upsert_participant(c,'ufc',names[0],'fighter'),None,'ufc',m.group(1),None,m.group(2),'ufcstats',fu)
                    add_snapshot(c,'ufc','ufcstats',fu,fr,date,hashlib.sha256(fx.encode()).hexdigest(),'UNVERIFIABLE')
                except Exception:pass
        add_snapshot(c,'ufc','ufcstats',u,r,date,hashlib.sha256(x.encode()).hexdigest(),'UNVERIFIABLE');c.commit();total+=1
    return total

def collect_rizin(c,h,max_pages=120):
    seeds=['https://jp.rizinff.com/','https://jp.rizinff.com/_tags/大会情報','https://jp.rizinff.com/_tags/試合結果']
    q=list(seeds);seen=set();total=0
    while q and len(seen)<max_pages:
        u=q.pop(0)
        if u in seen:continue
        seen.add(u)
        try:x,r,_=h.get(u)
        except Exception:continue
        s=BeautifulSoup(x,'lxml');title=clean(s.title.get_text(' ')) if s.title else u
        # Official RIZIN result/card pages expose fight pairs in article text even when JSON-LD is absent.
        candidates=[]
        for node in s.select('h1,h2,h3,h4,li,p'):
            t=clean(node.get_text(' '));
            if re.search(r'\bvs\b|\bVS\b|対',t) and len(t)<180:
                nn=extract_names(t)
                if len(nn)==2:candidates.append(nn)
        # Only treat article pages with multiple fight pairs as event pages.
        if len(candidates)>=2:
            m=re.search(r'(RIZIN[^\s|<]{0,30})',title,re.I);ename=clean(m.group(1)) if m else title
            date=None
            for z in jsonld(x):
                if z.get('datePublished'):date=iso(z['datePublished']);break
            eid=upsert_event(c,'rizin',ename,date,'jp.rizinff.com',u,'COMPLETED' if '結果' in title else 'SCHEDULED')
            for pair in candidates:
                for i,n in enumerate(pair):
                    pid=upsert_participant(c,'rizin',n,'fighter');upsert_ep(c,eid,pid,pid,'A' if i==0 else 'B',None,'jp.rizinff.com',u)
                total+=1
            add_snapshot(c,'rizin','jp.rizinff.com',u,r,date,hashlib.sha256(x.encode()).hexdigest(),'UNVERIFIABLE');c.commit()
        for a in s.find_all('a',href=True):
            v=urljoin(u,a['href'])
            if urlparse(v).netloc=='jp.rizinff.com' and v not in seen and ('_ct/' in v or 'rizin' in v.lower()):q.append(v)
    return total

def collect_volleyball(c,h,max_pages=100):
    seeds=['https://en.volleyballworld.com/volleyball/competitions','https://en.volleyballworld.com/volleyball/matches']
    q=list(seeds);seen=set();total=0
    while q and len(seen)<max_pages:
        u=q.pop(0)
        if u in seen:continue
        seen.add(u)
        try:x,r,_=h.get(u)
        except Exception:continue
        s=BeautifulSoup(x,'lxml')
        for z in jsonld(x):
            typ=str(z.get('@type',''))
            if typ not in ('SportsEvent','Event'):continue
            n=clean(z.get('name'));et=iso(z.get('startDate'));eid=upsert_event(c,'volleyball',n,et,'volleyballworld.com',u,'COMPLETED' if z.get('endDate') else 'SCHEDULED')
            teams=[]
            for k in ('homeTeam','awayTeam','competitor'):
                v=z.get(k);teams.extend(v if isinstance(v,list) else [v] if isinstance(v,dict) else [])
            for i,t in enumerate(teams[:2]):
                nm=clean(t.get('name') if isinstance(t,dict) else t)
                if nm:
                    pid=upsert_participant(c,'volleyball',nm,'team');upsert_ep(c,eid,pid,pid,'A' if i==0 else 'B',None,'volleyballworld.com',u)
            add_snapshot(c,'volleyball','volleyballworld.com',u,r,et,hashlib.sha256(x.encode()).hexdigest(),'UNVERIFIABLE');total+=1
        for a in s.find_all('a',href=True):
            v=urljoin(u,a['href'])
            if urlparse(v).netloc==urlparse(u).netloc and v not in seen and re.search(r'(match|matches|competition|tournament|game)',v,re.I):q.append(v)
    c.commit();return total

def main():
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--sport',choices=['valorant','ufc','rizin','volleyball']);ap.add_argument('--vlr-pages',type=int,default=180);ap.add_argument('--max-pages',type=int,default=120)
    a=ap.parse_args();c=connect();before={t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('event','participant','event_participant','match_stats','source_snapshot')};h=HTTP();done={};errors=[]
    jobs=[a.sport] if a.sport else ['valorant','ufc','rizin','volleyball']
    for sp in jobs:
        try:
            done[sp]=collect_vlr(c,h,a.vlr_pages) if sp=='valorant' else collect_ufc(c,h) if sp=='ufc' else collect_rizin(c,h,a.max_pages) if sp=='rizin' else collect_volleyball(c,h,a.max_pages)
        except Exception as e:errors.append({'sport':sp,'error':repr(e)})
    after={t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in before};c.commit();c.close()
    report={'parser_version':'v4.5.10-robust-adapter','done':done,'errors':errors,'before':before,'after':after,'deltas':{k:after[k]-before[k] for k in before},'timestamp_utc':utcnow()}
    p=ROOT/'results/robust_adapter.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(1 if errors else 0)
if __name__=='__main__':main()
