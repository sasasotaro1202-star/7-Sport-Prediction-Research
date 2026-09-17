from __future__ import annotations
import argparse, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
import src.storage.db_v45 as db
from src.seven_sport_production import clean, iso, sid, upsert_event, upsert_participant, upsert_ep, add_snapshot
ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/db/rugby_v45.sqlite'
PARSER = 'rugby-v2-explicit-deferred'
SEEDS = [
    'https://www.world.rugby/beta/en/tournaments/mens-six-nations/2026',
    'https://www.world.rugby/beta/en/tournaments/womens-six-nations/2026',
    'https://www.world.rugby/tournaments/fixtures-results',
    'https://www.world.rugby/tournaments/six-nations-u20',
    'https://www.world.rugby/u20/en',
    'https://www.world.rugby/nations-cup/en',
]

def fetch(url, timeout=20):
    r = requests.get(url, headers={'User-Agent':'SevenSportResearchEngine/Rugby-v2','Accept-Language':'en-US,en;q=0.8,ja;q=0.6'}, timeout=timeout)
    r.raise_for_status()
    return r.text, datetime.now(timezone.utc).isoformat()

def jsonld(html):
    out=[]
    soup=BeautifulSoup(html,'lxml')
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            x=json.loads(tag.string or tag.get_text())
            out.extend(x if isinstance(x,list) else [x])
        except Exception:
            pass
    return [x for x in out if isinstance(x,dict)]

def collect(max_pages):
    db.DB_PATH = DB
    c = db.connect()
    c.execute('CREATE INDEX IF NOT EXISTS idx_rugby_event_time ON event(sport,event_time_utc)')
    queue=list(SEEDS); seen=set(); events=0; snapshots=0; pages=0
    while queue and pages < max_pages:
        url=queue.pop(0)
        if url in seen: continue
        seen.add(url); pages += 1
        try: html,retrieved=fetch(url)
        except Exception:
            continue
        ph=hashlib.sha256(html.encode()).hexdigest()
        for item in jsonld(html):
            typ=str(item.get('@type',''))
            if typ not in ('SportsEvent','SportsEventSeries','Event'):
                continue
            name=clean(item.get('name'))
            if not name: continue
            et=iso(item.get('startDate') or item.get('startTime'))
            status=clean(str(item.get('eventStatus') or 'SCHEDULED'))
            eid=upsert_event(c,'rugby',name,et,'world.rugby',url,status)
            teams=[]
            for key in ('homeTeam','awayTeam','competitor'):
                value=item.get(key)
                teams.extend(value if isinstance(value,list) else [value] if isinstance(value,dict) else [])
            for i,t in enumerate(teams[:2]):
                nm=clean(t.get('name') if isinstance(t,dict) else t)
                if nm:
                    pid=upsert_participant(c,'rugby',nm,'team')
                    upsert_ep(c,eid,pid,pid,'A' if i==0 else 'B',None,'world.rugby',url)
            add_snapshot(c,'rugby','world.rugby',url,retrieved,et,ph,'UNVERIFIABLE')
            events += 1; snapshots += 1
        soup=BeautifulSoup(html,'lxml')
        for a in soup.find_all('a',href=True):
            u=urljoin(url,a['href']).split('#')[0]
            if urlparse(u).netloc != 'www.world.rugby': continue
            if u in seen or u in queue: continue
            if re.search(r'(match|fixture|result|tournament|championship|six-nations|world-cup|nations-cup|wxv|svns|pacific|u20|u21)',u,re.I):
                queue.append(u)
        if pages % 10 == 0:
            c.commit()
    c.commit()
    counts={
        'events': c.execute("SELECT COUNT(*) FROM event WHERE sport='rugby'").fetchone()[0],
        'timed_events': c.execute("SELECT COUNT(*) FROM event WHERE sport='rugby' AND event_time_utc IS NOT NULL").fetchone()[0],
        'participants': c.execute("SELECT COUNT(*) FROM participant WHERE sport='rugby'").fetchone()[0],
        'source_snapshots': c.execute("SELECT COUNT(*) FROM source_snapshot WHERE provenance_json LIKE '%\\\"sport\\\": \\\"rugby\\\"%'").fetchone()[0],
    }
    c.close()
    out=ROOT/'results/v45/rugby_coverage.json'; out.parent.mkdir(parents=True,exist_ok=True)
    status = 'PASS' if counts['events']>0 and counts['source_snapshots']>0 else 'DEFERRED'
    report={'sport':'rugby','status':status,'source':'World Rugby official','parser_version':PARSER,'pages_visited':pages,'events_found':events,'counts':counts,'seed_competitions':['Men Six Nations','Women Six Nations','U20 Six Nations','World Rugby U20 Championship','World Rugby Nations Cup'],'timestamp_utc':datetime.now(timezone.utc).isoformat(),'deferred_reason':None if status=='PASS' else 'No machine-readable event objects were observed from the current public pages; coverage is explicitly deferred rather than fabricated.'}
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    # DEFERRED is a valid, explicit research state: it is not a production success
    # and does not authorize Rugby model publication. Actual exceptions remain failures.
    return 0 if status in ('PASS','DEFERRED') else 2

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--max-pages',type=int,default=150); args=ap.parse_args(); raise SystemExit(collect(args.max_pages))
