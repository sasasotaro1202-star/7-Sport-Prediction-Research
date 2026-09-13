from __future__ import annotations
import hashlib, json, os, re, sqlite3, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote
import csv, io
import requests
from bs4 import BeautifulSoup

from src.storage.db_v45 import connect, utcnow
from src.seven_sport_production import upsert_event, upsert_participant, upsert_ep, add_stat, add_snapshot

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/db/sports_v45.sqlite'
UA = os.getenv('SPORTS_PIPELINE_USER_AGENT', 'SevenSportResearchEngine/4.5.10-robust-adapter-v2')
JINA = 'https://r.jina.ai/http://'

class HTTP:
    def __init__(self):
        self.timeout=float(os.getenv('V45_HTTP_TIMEOUT','20'))
        self.retries=int(os.getenv('V45_HTTP_RETRIES','3'))
        self.delay=float(os.getenv('V45_REQUEST_DELAY','0.08'))
        self.workers=max(2,int(os.getenv('V45_HTTP_WORKERS','12')))
        self.cache=ROOT/'data/raw/http_cache'
        self.cache.mkdir(parents=True,exist_ok=True)
    def get(self,url,use_cache=True):
        key=hashlib.sha256(url.encode()).hexdigest()
        p=self.cache/(key+'.json')
        if use_cache and p.exists():
            try:
                x=json.loads(p.read_text(encoding='utf-8'))
                if x.get('status')==200 and x.get('text') is not None:return x['text'],x.get('retrieved_at_utc'),x.get('headers',{}),x.get('via','direct')
            except Exception:pass
        last=None
        for i in range(self.retries+1):
            try:
                if self.delay:time.sleep(self.delay)
                r=requests.get(url,headers={'User-Agent':UA,'Accept-Language':'en-US,en;q=0.8,ja;q=0.7'},timeout=self.timeout)
                r.raise_for_status();txt=r.text;now=utcnow()
                obj={'status':r.status_code,'text':txt,'retrieved_at_utc':now,'headers':dict(r.headers),'via':'direct'}
                try:p.write_text(json.dumps(obj,ensure_ascii=False),encoding='utf-8')
                except Exception:pass
                return txt,now,dict(r.headers),'direct'
            except Exception as e:last=e
        # Browser-facing sources frequently block datacenter IPs. Jina Reader is a
        # bounded retrieval fallback; the provenance still retains the canonical URL.
        try:
            proxy=JINA+url.replace('https://','').replace('http://','')
            r=requests.get(proxy,headers={'User-Agent':UA},timeout=max(self.timeout,30))
            r.raise_for_status();txt=r.text;now=utcnow()
            obj={'status':r.status_code,'text':txt,'retrieved_at_utc':now,'headers':dict(r.headers),'via':'jina_reader'}
            try:p.write_text(json.dumps(obj,ensure_ascii=False),encoding='utf-8')
            except Exception:pass
            return txt,now,dict(r.headers),'jina_reader'
        except Exception:pass
        raise last or RuntimeError(f'GET failed: {url}')
    def many(self,urls):
        out={}
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            fs={ex.submit(self.get,u):u for u in urls}
            for f in as_completed(fs):
                u=fs[f]
                try:out[u]=f.result()
                except Exception:out[u]=None
        return out

def iso(v):
    if not v:return None
    s=str(v).strip().replace('Z','+00:00')
    for fmt in ('%B %d, %Y','%b %d, %Y','%Y-%m-%d'):
        try:return datetime.strptime(s,fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:pass
    try:
        d=datetime.fromisoformat(s)
        if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:return None

def clean(x):return re.sub(r'\s+',' ',str(x or '')).strip()

def snapshot(c,sport,source,url,retrieved,et,text,via):
    add_snapshot(c,sport,source,url,retrieved,et,hashlib.sha256(text.encode()).hexdigest(),'UNVERIFIABLE')
    # Preserve retrieval-route evidence separately without weakening PIT policy.
    try:
        c.execute("UPDATE source_snapshot SET provenance_json=? WHERE source_url=?",(json.dumps({'sport':sport,'retrieval_route':via,'canonical_url':url,'parser':'v4.5.10-robust-adapter-v2'},ensure_ascii=False),url))
    except Exception:pass

def collect_vlr(c,h,pages=180):
    total=0
    for page in range(1,pages+1):
        url='https://www.vlr.gg/matches/'+(f'?page={page}' if page>1 else '')
        try:html,r,_,via=h.get(url)
        except Exception:continue
        # Direct HTML and Jina markdown both expose canonical match URLs.
        links=list(dict.fromkeys(re.findall(r'https?://www\.vlr\.gg/match/\d+(?:/[^\s)"<>]+)?',html)))
        links += [urljoin(url,x) for x in re.findall(r'href=["\']([^"\']*/match/\d+[^"\']*)',html)]
        links=list(dict.fromkeys(links))
        if not links:continue
        for u,res in h.many(links).items():
            if not res:continue
            x,rr,_,v=res
            m=re.search(r'/match/(\d+)/([^/?#\s)]+)',u)
            slug=clean((m.group(2) if m else '').replace('-',' '))
            title=slug or u
            for z in re.findall(r'([^\n]{2,80})\s+vs\.?\s+([^\n]{2,80})',x,re.I):
                title=f'{clean(z[0])} vs {clean(z[1])}';break
            et=None
            for pat in (r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)',r'(\w{3}\s+\d{1,2},\s+\d{4})'):
                mm=re.search(pat,x)
                if mm:et=iso(mm.group(1));break
            eid=upsert_event(c,'valorant',title,et,'vlr.gg',u,'COMPLETED' if re.search(r'Completed|Final|finished',x,re.I) else 'SCHEDULED')
            names=[]
            # Canonical page title/slug gives reliable team pair for the majority of matches.
            if ' vs ' in title:names=[clean(q) for q in re.split(r'\s+vs\.?\s+',title,flags=re.I)[:2]]
            for i,n in enumerate(names[:2]):
                if len(n)>1:
                    pid=upsert_participant(c,'valorant',n,'team');upsert_ep(c,eid,pid,pid,'A' if i==0 else 'B',None,'vlr.gg',u)
            snapshot(c,'valorant','vlr.gg',u,rr,et,x,v);total+=1
        c.commit()
    return total

def collect_ufc_dataset(c,h):
    # Stable historical fallback published by TidyTuesday on 2026-07-07 and sourced from UFCStats.
    base='https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/data/2026/2026-07-07/ufc_fights.csv'
    try:raw,r,_,via=h.get(base)
    except Exception:return 0
    rows=list(csv.DictReader(io.StringIO(raw)));total=0
    published='2026-07-07T00:00:00+00:00'
    for row in rows:
        date=row.get('date');name=clean(row.get('event_name'));f1=clean(row.get('f1_name'));f2=clean(row.get('f2_name'))
        if not name or not f1 or not f2:continue
        et=iso(date);eid=upsert_event(c,'ufc',name,et,'ufcstats-tidytuesday',row.get('fight_url') or base,'COMPLETED' if row.get('f1_result') else 'SCHEDULED')
        p1=upsert_participant(c,'ufc',f1,'fighter');p2=upsert_participant(c,'ufc',f2,'fighter')
        upsert_ep(c,eid,p1,p1,'A',None,'ufcstats-tidytuesday',row.get('fight_url') or base)
        upsert_ep(c,eid,p2,p2,'B',None,'ufcstats-tidytuesday',row.get('fight_url') or base)
        for key,val in row.items():
            if key in ('f1_name','f2_name','event_name','fight_url','date'):continue
            try:num=float(val) if val not in ('',None) else None
            except Exception:num=None
            if num is not None or val:
                add_stat(c,eid,p1,p1,'ufc',f'A.{key}',num,str(val) if val is not None else None,'ufcstats-tidytuesday',row.get('fight_url') or base)
        total+=1
    c.commit()
    # The dataset publication date is an evidence boundary; do not use retrieval time as publication time.
    try:
        c.execute("UPDATE source_snapshot SET source_available_at_utc=? WHERE source_url=?",(published,base))
        snapshot(c,'ufc','ufcstats-tidytuesday',base,r,None,raw,via)
        c.execute("UPDATE source_snapshot SET source_available_at_utc=? WHERE source_url=?",(published,base))
        c.commit()
    except Exception:pass
    return total

def collect_rizin(c,h,max_pages=120):
    # Keep the proven official-site adapter from v1; v2 adds the same bounded route fallback.
    seeds=['https://jp.rizinff.com/','https://jp.rizinff.com/_tags/大会情報','https://jp.rizinff.com/_tags/試合結果']
    q=list(seeds);seen=set();total=0
    while q and len(seen)<max_pages:
        u=q.pop(0)
        if u in seen:continue
        seen.add(u)
        try:x,r,_,via=h.get(u)
        except Exception:continue
        s=BeautifulSoup(x,'lxml');title=clean(s.title.get_text(' ')) if s.title else u
        candidates=[]
        for node in s.select('h1,h2,h3,h4,li,p'):
            t=clean(node.get_text(' '))
            parts=re.split(r'\s+vs\.?\s+|\s+対\s+',t,flags=re.I)
            if len(parts)==2 and all(len(z)>=2 for z in parts):candidates.append([clean(parts[0]),clean(parts[1])])
        if len(candidates)>=2:
            date=None
            for z in re.findall(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}',x):date=iso(z);break
            eid=upsert_event(c,'rizin',title,date,'jp.rizinff.com',u,'COMPLETED' if re.search(r'結果|result',title,re.I) else 'SCHEDULED')
            for pair in candidates:
                for i,n in enumerate(pair):
                    pid=upsert_participant(c,'rizin',n,'fighter');upsert_ep(c,eid,pid,pid,'A' if i==0 else 'B',None,'jp.rizinff.com',u)
                total+=1
            snapshot(c,'rizin','jp.rizinff.com',u,r,date,x,via);c.commit()
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
        try:x,r,_,via=h.get(u)
        except Exception:continue
        s=BeautifulSoup(x,'lxml')
        for z in [] if not isinstance(x,str) else []:pass
        # JSON-LD path for normal HTML; fallback text path for browser-rendered pages.
        for z in re.findall(r'\"name\"\s*:\s*\"([^\"]+)\"[^\n]{0,500}?\"startDate\"\s*:\s*\"([^\"]+)\"',x):
            n,dt=z;eid=upsert_event(c,'volleyball',clean(n),iso(dt),'volleyballworld.com',u,'SCHEDULED')
            snapshot(c,'volleyball','volleyballworld.com',u,r,iso(dt),x,via);total+=1
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
            if sp=='valorant':done[sp]=collect_vlr(c,h,a.vlr_pages)
            elif sp=='ufc':done[sp]=collect_ufc_dataset(c,h)
            elif sp=='rizin':done[sp]=collect_rizin(c,h,a.max_pages)
            else:done[sp]=collect_volleyball(c,h,a.max_pages)
        except Exception as e:errors.append({'sport':sp,'error':repr(e)})
    after={t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in before};c.commit();c.close()
    report={'parser_version':'v4.5.10-robust-adapter-v2','done':done,'errors':errors,'before':before,'after':after,'deltas':{k:after[k]-before[k] for k in before},'timestamp_utc':utcnow()}
    p=ROOT/'results/robust_adapter.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(1 if errors else 0)
if __name__=='__main__':main()
