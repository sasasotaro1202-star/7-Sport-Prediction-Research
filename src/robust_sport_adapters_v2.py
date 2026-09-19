from __future__ import annotations
import hashlib, json, os, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import csv, io
import requests
from bs4 import BeautifulSoup

from src.storage.db_v45 import connect, utcnow
from src.seven_sport_production import upsert_event, upsert_participant, upsert_ep, add_stat, add_snapshot

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/db/sports_v45.sqlite'
UA = os.getenv('SPORTS_PIPELINE_USER_AGENT', 'SevenSportResearchEngine/4.5.12-robust-adapter-v3')
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
        key=hashlib.sha256(url.encode()).hexdigest(); p=self.cache/(key+'.json')
        if use_cache and p.exists():
            try:
                x=json.loads(p.read_text(encoding='utf-8'))
                if x.get('status')==200 and x.get('text') is not None:return x['text'],x.get('retrieved_at_utc'),x.get('headers',{}),x.get('via','direct')
            except Exception:pass
        last=None
        for _ in range(self.retries+1):
            try:
                if self.delay:time.sleep(self.delay)
                r=requests.get(url,headers={'User-Agent':UA,'Accept-Language':'en-US,en;q=0.8,ja;q=0.7'},timeout=self.timeout)
                r.raise_for_status();txt=r.text;now=utcnow()
                try:p.write_text(json.dumps({'status':r.status_code,'text':txt,'retrieved_at_utc':now,'headers':dict(r.headers),'via':'direct'},ensure_ascii=False),encoding='utf-8')
                except Exception:pass
                return txt,now,dict(r.headers),'direct'
            except Exception as e:last=e
        try:
            proxy=JINA+url.replace('https://','').replace('http://','')
            r=requests.get(proxy,headers={'User-Agent':UA},timeout=max(self.timeout,30));r.raise_for_status();txt=r.text;now=utcnow()
            try:p.write_text(json.dumps({'status':r.status_code,'text':txt,'retrieved_at_utc':now,'headers':dict(r.headers),'via':'jina_reader'},ensure_ascii=False),encoding='utf-8')
            except Exception:pass
            return txt,now,dict(r.headers),'jina_reader'
        except Exception:pass
        raise last or RuntimeError(f'GET failed: {url}')
    def many(self,urls):
        out={}
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            fs={ex.submit(self.get,u):u for u in urls}
            for f in as_completed(fs):
                try:out[fs[f]]=f.result()
                except Exception:out[fs[f]]=None
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

def extract_published_at(text):
    patterns=(r'property=["\']article:published_time["\'][^>]*content=["\']([^"\']+)',r'name=["\']datePublished["\'][^>]*content=["\']([^"\']+)',r'itemprop=["\']datePublished["\'][^>]*content=["\']([^"\']+)',r'"datePublished"\s*:\s*"([^"]+)"',r'"publishedAt"\s*:\s*"([^"]+)"',r'Published\s+([^<\n]{8,40})',r'公開日[：:]\s*([^<\n]{8,30})')
    for pat in patterns:
        m=re.search(pat,text or '',re.I)
        if m:
            v=iso(m.group(1))
            if v:return v
    return None

def snapshot(c,sport,source,url,retrieved,et,text,via):
    published=extract_published_at(text); status='EXACT' if published else 'UNVERIFIABLE'
    add_snapshot(c,sport,source,url,retrieved,et,hashlib.sha256(text.encode()).hexdigest(),status)
    try:c.execute("UPDATE source_snapshot SET provenance_json=?, source_available_at_utc=? WHERE source_url=?",(json.dumps({'sport':sport,'retrieval_route':via,'canonical_url':url,'parser':'v4.5.12-robust-adapter-v3','publication_evidence':'explicit_page_metadata' if published else None},ensure_ascii=False),published,url))
    except Exception:pass

def collect_vlr(c,h,pages=180):
    """Collect VLR historical results and repair legacy untimed rows by URL."""
    total=0
    for page in range(1,pages+1):
        url='https://www.vlr.gg/matches/results'+(f'/?page={page}' if page>1 else '')
        try:
            html,r,_,via=h.get(url)
        except Exception:
            continue
        links=list(dict.fromkeys(re.findall(r'https?://www\.vlr\.gg/match/\d+(?:/[^\s)"<>]+)?',html)))
        links += [urljoin(url,x) for x in re.findall(r"href=['\"]([^'\"]*/match/\d+[^'\"]*)",html)]
        links=list(dict.fromkeys(links))
        if not links:
            continue
        for u,res in h.many(links).items():
            if not res:
                continue
            x,rr,_,v=res
            m=re.search(r'/match/(\d+)/([^/?#\s)]+)',u)
            title=clean((m.group(2) if m else '').replace('-',' ')) or u
            for z in re.findall(r'([^\n]{2,80})\s+vs\.?\s+([^\n]{2,80})',x,re.I):
                title=f'{clean(z[0])} vs {clean(z[1])}'
                break
            et=None
            tm=re.search(r"(?:data-game-time|data-utc-ts)=['\"](\d{9,})['\"]",x)
            if tm:
                try:
                    et=datetime.fromtimestamp(int(tm.group(1)),tz=timezone.utc).isoformat()
                except Exception:
                    et=None
            if et is None:
                mm=re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)',x)
                if mm:
                    et=iso(mm.group(1))
            existing=c.execute("SELECT event_id FROM event WHERE sport='valorant' AND source='vlr.gg' AND source_url=? ORDER BY updated_at DESC LIMIT 1",(u,)).fetchone()
            if existing and et:
                eid=existing[0]
                c.execute("UPDATE event SET event_time_utc=?, status='COMPLETED', updated_at=? WHERE event_id=?",(et,utcnow(),eid))
            else:
                eid=upsert_event(c,'valorant',title,et,'vlr.gg',u,'COMPLETED')
            names=[clean(q) for q in re.split(r'\s+vs\.?\s+',title,flags=re.I)[:2]] if ' vs ' in title else []
            for i,n in enumerate(names[:2]):
                if len(n)>1:
                    pid=upsert_participant(c,'valorant',n,'team')
                    upsert_ep(c,eid,pid,pid,'A' if i==0 else 'B',None,'vlr.gg',u)
            snapshot(c,'valorant','vlr.gg',u,rr,et,x,v)
            if et:
                c.execute("UPDATE source_snapshot SET event_time_utc=? WHERE source_url=?",(et,u))
            total+=1
        c.commit()
    # Repair ALL legacy VLR rows already in the canonical DB that lack event_time_utc.
    # This bypasses the limited recent-results page window and uses only explicit VLR
    # detail-page timestamps, preserving the existing provenance/cache path.
    rows=c.execute("SELECT event_id,source_url FROM event WHERE sport='valorant' AND source='vlr.gg' AND (event_time_utc IS NULL OR TRIM(event_time_utc)='') AND source_url IS NOT NULL ORDER BY event_id").fetchall()
    by_url={u:eid for eid,u in rows}
    repaired=0
    for u,res in h.many([u for _,u in rows]).items():
        if not res:
            continue
        x,rr,_,v=res
        tm=re.search(r"(?:data-game-time|data-utc-ts)=['\"](\d{9,})['\"]",x)
        et=None
        if tm:
            try:
                et=datetime.fromtimestamp(int(tm.group(1)),tz=timezone.utc).isoformat()
            except Exception:
                et=None
        if et is None:
            mm=re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)',x)
            if mm:
                et=iso(mm.group(1))
        eid=by_url.get(u)
        if not eid or not et:
            continue
        c.execute("UPDATE event SET event_time_utc=?, status='COMPLETED', updated_at=? WHERE event_id=?",(et,utcnow(),eid))
        snapshot(c,'valorant','vlr.gg',u,rr,et,x,v)
        c.execute("UPDATE source_snapshot SET event_time_utc=? WHERE source_url=?",(et,u))
        repaired+=1
        if repaired % 250 == 0:
            c.commit()
    c.commit()
    return total + repaired
def collect_ufc_dataset(c,h):
    base='https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/data/2026/2026-07-07/ufc_fights.csv'
    try:raw,r,_,via=h.get(base)
    except Exception:return 0
    rows=list(csv.DictReader(io.StringIO(raw)));total=0;published='2026-07-07T00:00:00+00:00'
    for row in rows:
        date=row.get('date');name=clean(row.get('event_name'));f1=clean(row.get('f1_name'));f2=clean(row.get('f2_name'))
        if not name or not f1 or not f2:continue
        et=iso(date);url=row.get('fight_url') or base;eid=upsert_event(c,'ufc',f'{name} | {f1} vs {f2}',et,'ufcstats-tidytuesday',url,'COMPLETED' if row.get('f1_result') else 'SCHEDULED',competition=name,season=str(date)[:4] if date else None)
        p1=upsert_participant(c,'ufc',f1,'fighter');p2=upsert_participant(c,'ufc',f2,'fighter');upsert_ep(c,eid,p1,p1,'A','fight','ufcstats-tidytuesday',url);upsert_ep(c,eid,p2,p2,'B','fight','ufcstats-tidytuesday',url)
        for key,val in row.items():
            if key in ('f1_name','f2_name','event_name','fight_url','date'):continue
            try:num=float(val) if val not in ('',None) else None
            except Exception:num=None
            if num is not None or val:
                side='A' if key.startswith('f1_') else 'B' if key.startswith('f2_') else 'META';pid=p1 if side!='B' else p2
                add_stat(c,eid,pid,pid,'ufc',f'fight.{side}.{key}',num,str(val) if val is not None else None,'ufcstats-tidytuesday',url)
        total+=1
    c.commit();snapshot(c,'ufc','ufcstats-tidytuesday',base,r,None,raw,via);c.execute("UPDATE source_snapshot SET source_available_at_utc=?, availability_status='EXACT' WHERE source_url=?",(published,base));c.commit();return total

def collect_rizin(c,h,max_pages=120):
    seeds=['https://jp.rizinff.com/_tags/試合結果','https://jp.rizinff.com/_tags/対戦カード'];seen=set();queue=list(seeds);links=[]
    while queue and len(seen)<max_pages:
        u=queue.pop(0)
        if u in seen:continue
        seen.add(u)
        try:x,r,_,via=h.get(u)
        except Exception:continue
        for a in re.findall(r'href=["\']([^"\']+)["\']',x,re.I):
            v=urljoin(u,a)
            if urlparse(v).netloc=='jp.rizinff.com' and '_ct/' in v and v not in links:links.append(v)
    total=0
    for u,res in h.many(list(dict.fromkeys(links))).items():
        if not res:continue
        x,r,_,via=res
        if 'WIN' not in x or 'LOSE' not in x:continue
        tm=re.search(r'<title[^>]*>(.*?)</title>',x,re.I|re.S);title=clean(tm.group(1) if tm else u)
        m=re.search(r'(?:第\d+試合／)?\s*([^<\n|｜]{2,80}?)\s+vs\.?\s+([^<\n|｜]{2,80})',title,re.I) or re.search(r'([^<\n]{2,80})\s+vs\.?\s+([^<\n]{2,80})',x,re.I)
        if not m:continue
        a,b=clean(m.group(1)),clean(m.group(2));win=re.search(r'\(WIN\)\s*([^<\n]{2,80})\s+vs\.?\s+([^<\n]{2,80})\s*\(LOSE\)',x,re.I)
        if not win:continue
        wa,wb=clean(win.group(1)),clean(win.group(2));outcome='A' if wa==a else 'B' if wb==a else 'A' if wa==b else 'B';pub=extract_published_at(x);et=iso(re.search(r'(20\d{2}[./-]\d{1,2}[./-]\d{1,2})',x).group(1)) if re.search(r'(20\d{2}[./-]\d{1,2}[./-]\d{1,2})',x) else None
        eid=upsert_event(c,'rizin',f'{a} vs {b}',et,'jp.rizinff.com',u,'COMPLETED',competition=title);p1=upsert_participant(c,'rizin',a,'fighter');p2=upsert_participant(c,'rizin',b,'fighter');upsert_ep(c,eid,p1,p1,'A','fight','jp.rizinff.com',u);upsert_ep(c,eid,p2,p2,'B','fight','jp.rizinff.com',u)
        c.execute('''INSERT OR REPLACE INTO event_outcome (event_id,sport,side_a_participant_id,side_b_participant_id,outcome,score_a,score_b,outcome_status,source,source_url,observed_at_utc,quality_status,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(eid,'rizin',p1,p2,outcome,None,None,'VERIFIED','jp.rizinff.com',u,utcnow(),'PIT_REQUIRES_REPLAY','Official result page'))
        if pub:
            add_snapshot(c,'rizin','jp.rizinff.com',u,r,et,hashlib.sha256(x.encode()).hexdigest(),'EXACT');c.execute("UPDATE source_snapshot SET source_available_at_utc=?, provenance_json=? WHERE source_url=?",(pub,json.dumps({'publication_evidence':'explicit_page_metadata','parser':'v4.5.12-rizin-fight-level'},ensure_ascii=False),u))
        else:snapshot(c,'rizin','jp.rizinff.com',u,r,et,x,via)
        total+=1
    c.commit();return total

def collect_volleyball(c,h,max_pages=100):
    seeds=['https://en.volleyballworld.com/volleyball/competitions','https://en.volleyballworld.com/volleyball/matches'];q=list(seeds);seen=set();total=0
    while q and len(seen)<max_pages:
        u=q.pop(0)
        if u in seen:continue
        seen.add(u)
        try:x,r,_,via=h.get(u)
        except Exception:continue
        s=BeautifulSoup(x,'lxml')
        for n,dt in re.findall(r'\"name\"\s*:\s*\"([^\"]+)\"[^\n]{0,500}?\"startDate\"\s*:\s*\"([^\"]+)\"',x):
            eid=upsert_event(c,'volleyball',clean(n),iso(dt),'volleyballworld.com',u,'SCHEDULED');snapshot(c,'volleyball','volleyballworld.com',u,r,iso(dt),x,via);total+=1
        for a in s.find_all('a',href=True):
            v=urljoin(u,a['href'])
            if urlparse(v).netloc==urlparse(u).netloc and v not in seen and re.search(r'(match|matches|competition|tournament|game)',v,re.I):q.append(v)
    c.commit();return total

def main():
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--sport',choices=['valorant','ufc','rizin','volleyball']);ap.add_argument('--vlr-pages',type=int,default=180);ap.add_argument('--max-pages',type=int,default=120);a=ap.parse_args();c=connect();before={t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('event','participant','event_participant','match_stats','source_snapshot')};h=HTTP();done={};errors=[];jobs=[a.sport] if a.sport else ['valorant','ufc','rizin','volleyball']
    for sp in jobs:
        try:done[sp]=collect_vlr(c,h,a.vlr_pages) if sp=='valorant' else collect_ufc_dataset(c,h) if sp=='ufc' else collect_rizin(c,h,a.max_pages) if sp=='rizin' else collect_volleyball(c,h,a.max_pages)
        except Exception as e:errors.append({'sport':sp,'error':repr(e)})
    after={t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in before};c.commit();c.close();report={'parser_version':'v4.5.12-robust-adapter-v3','done':done,'errors':errors,'before':before,'after':after,'deltas':{k:after[k]-before[k] for k in before},'timestamp_utc':utcnow()};p=ROOT/'results/robust_adapter.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(1 if errors else 0)
if __name__=='__main__':main()
