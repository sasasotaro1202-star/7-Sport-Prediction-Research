from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from src.seven_sport_production import add_snapshot, upsert_ep, upsert_event, upsert_participant
from src.storage.db_v45 import connect, utcnow

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "db" / "sports_v45.sqlite"
OUT = ROOT / "results" / "bleague_upcoming_predictions.json"
BASE = "https://www.bleague.jp"
SCHEDULE = BASE + "/schedule/?mon={month:02d}&tab={tab}&year=2026"
UA = "SevenSportResearchEngine/bleague-production-v2"
JST = ZoneInfo("Asia/Tokyo")

def get(url: str):
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}, timeout=30)
    r.raise_for_status()
    return r.text, utcnow()

def parse_detail(html: str, url: str):
    soup = BeautifulSoup(html, 'lxml')
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = soup.get_text(" ", strip=True)
    blob = title + ' ' + text
    dm = re.search(r'(2026[./-]\d{1,2}[./-]\d{1,2})', blob)
    tm = re.search(r'(\d{1,2}:\d{2})\s*(?:TIP OFF|TIPOFF|ティップオフ)', blob, re.I)
    vm = re.search(r'(?:2026[./-]\d{1,2}[./-]\d{1,2})\s+(.+?)\s+VS\s+(.+?)(?:\s+チケット|\s+Buy|\s*$)', title, re.I)
    if not vm:
        vm = re.search(r'(?:2026[./-]\d{1,2}[./-]\d{1,2})\s+(.+?)\s+VS\s+(.+?)(?:\s+\|\s+|\s+チケット|$)', blob, re.I)
    if not (dm and vm):
        return None
    compm = re.search(r'\b(B\.PREMIER|B\.ONE|B\.NEXT)\b', blob)
    home = re.sub(r'^.*?リーグ戦\s*', '', vm.group(1)).strip()
    away = vm.group(2).strip()
    home = re.sub(r'\s+(B\.PREMIER|B\.ONE|B\.NEXT)\s*$', '', home).strip()
    away = re.sub(r'\s+(B\.PREMIER|B\.ONE|B\.NEXT)\s*$', '', away).strip()
    if not home or not away or home == away:
        return None
    return {'date': dm.group(1), 'time': tm.group(1) if tm else None, 'home': home, 'away': away,
            'competition': compm.group(1) if compm else 'B.LEAGUE', 'url': url}

def to_utc(date_s: str, time_s: str | None):
    m = re.search(r'2026[./-](\d{1,2})[./-](\d{1,2})', date_s)
    if not m:
        return None
    hh, mm = (int(x) for x in (time_s or '00:00').split(':', 1))
    month, day = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    dt = datetime(2026, month, day, hh, mm, tzinfo=JST)
    return dt.astimezone(timezone.utc).isoformat()

def main():
    now = datetime.now(timezone.utc)
    until = datetime(2026, 10, 4, 23, 59, 59, tzinfo=JST).astimezone(timezone.utc)
    c = connect()
    links = set()
    schedule_snapshots = []
    try:
        for month in (9, 10):
            for tab in (1, 2, 3):
                url = SCHEDULE.format(month=month, tab=tab)
                try:
                    html, retrieved = get(url)
                except Exception as exc:
                    schedule_snapshots.append({'url': url, 'error': type(exc).__name__})
                    continue
                schedule_snapshots.append({'url': url, 'retrieved_at_utc': retrieved})
                soup = BeautifulSoup(html, 'lxml')
                for a in soup.find_all('a', href=re.compile(r'game_detail')):
                    href = a.get('href', '')
                    if href.startswith('/'):
                        href = BASE + href
                    if 'game_detail' in href:
                        links.add(href.split('#')[0])
                add_snapshot(c, 'basketball', 'bleague-official', url, retrieved, None,
                             hashlib.sha256(html.encode('utf-8', 'ignore')).hexdigest(),
                             'EXACT', source_available_at_utc=retrieved)
        games=[]
        for url in sorted(links):
            try:
                html, retrieved = get(url)
                item = parse_detail(html, url)
            except Exception:
                continue
            if not item:
                continue
            et = to_utc(item['date'], item['time'])
            if not et:
                continue
            edt = datetime.fromisoformat(et.replace('Z', '+00:00'))
            if edt <= now or edt > until:
                continue
            eid = upsert_event(c, 'basketball', f"{item['home']} vs {item['away']}", et,
                               'bleague-official', url, 'SCHEDULED',
                               competition=item['competition'], season='2026-27')
            p1 = upsert_participant(c, 'basketball', item['home'], 'team')
            p2 = upsert_participant(c, 'basketball', item['away'], 'team')
            upsert_ep(c, eid, p1, p1, 'A', 'match', 'bleague-official', url)
            upsert_ep(c, eid, p2, p2, 'B', 'match', 'bleague-official', url)
            games.append({'event_id': eid, 'event_time_utc': et, 'home': item['home'],
                          'away': item['away'], 'competition': item['competition'], 'url': url})
        c.commit()
    finally:
        c.close()
    subprocess.run(['python','-m','src.future_predictor','--sport','basketball',
                    '--until-utc',until.isoformat()], check=True)
    report=json.loads((ROOT/'results'/'future_predictions.json').read_text(encoding='utf-8'))
    pred=next((x for x in report['sports'] if x.get('sport')=='basketball'),{})
    out={'generated_at_utc':report['generated_at_utc'],'window_end_utc':until.isoformat(),
         'source':'B.LEAGUE official schedule/game_detail pages','production_policy':report['policy'],
         'schedule_page_snapshots':schedule_snapshots,'schedule_games':games,
         'prediction_status':pred.get('status'),'predictions':pred.get('predictions',[]),
         'count':pred.get('count',0)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()