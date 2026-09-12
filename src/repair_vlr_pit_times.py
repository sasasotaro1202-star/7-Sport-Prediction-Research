from __future__ import annotations
import argparse, hashlib, json, re, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from src.storage.db_v45 import connect

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/db/sports_v45.sqlite'


def iso(v):
    if not v:
        return None
    s = str(v).strip().replace('Z', '+00:00')
    for fmt in (None,):
        try:
            d = datetime.fromisoformat(s)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d.astimezone(timezone.utc).isoformat()
        except Exception:
            pass
    return None


def jsonld(html):
    soup = BeautifulSoup(html, 'lxml')
    out = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            obj = json.loads(node.string or node.get_text())
            out.extend(obj if isinstance(obj, list) else [obj])
        except Exception:
            continue
    return [x for x in out if isinstance(x, dict)]


def parse_time(html):
    for x in jsonld(html):
        if x.get('startDate'):
            v = iso(x['startDate'])
            if v:
                return v
    soup = BeautifulSoup(html, 'lxml')
    for sel in ('.match-header-date-item', '.match-header-link-date', '.match-header-date'):
        node = soup.select_one(sel)
        if not node:
            continue
        txt = ' '.join(node.stripped_strings)
        # VLR embeds epoch seconds in data attributes on some layouts.
        for attr in ('data-unix', 'data-time', 'data-timestamp'):
            raw = node.get(attr)
            if raw and re.fullmatch(r'\d{9,13}', raw):
                n = int(raw)
                if n > 10_000_000_000:
                    n //= 1000
                return datetime.fromtimestamp(n, tz=timezone.utc).isoformat()
        # Avoid inventing a date from a clock-only string.
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--timeout', type=float, default=12)
    args = ap.parse_args()
    c = connect()
    rows = c.execute("SELECT event_id, source_url FROM event WHERE sport='valorant' AND event_time_utc IS NULL AND source_url IS NOT NULL").fetchall()
    repaired = 0
    rejected = 0
    import requests
    for eid, url in rows:
        try:
            r = requests.get(url, timeout=args.timeout, headers={'User-Agent':'SevenSportResearchEngine/4.5.11'})
            r.raise_for_status()
            et = parse_time(r.text)
            if not et:
                rejected += 1
                continue
            c.execute("UPDATE event SET event_time_utc=?, quality_status='PRESENT_NOT_PIT_VERIFIED', updated_at=? WHERE event_id=?", (et, datetime.now(timezone.utc).isoformat(), eid))
            c.execute("UPDATE source_snapshot SET event_time_utc=? WHERE source_url=? AND source='vlr.gg'", (et, url))
            repaired += 1
        except Exception:
            rejected += 1
    c.commit()
    c.close()
    print(json.dumps({'sport':'valorant','repaired':repaired,'unresolved':rejected,'candidate_rows':len(rows)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
