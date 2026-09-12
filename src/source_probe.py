from __future__ import annotations
import argparse, json, os, time
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
SPORTS = ('valorant','basketball','volleyball','tennis','ufc','rizin','f1')

SOURCES = {
    'valorant': [
        'https://www.vlr.gg/matches/',
    ],
    'basketball': [
        'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard',
        'https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard',
    ],
    'volleyball': [
        'https://en.volleyballworld.com/volleyball/competitions',
        'https://en.volleyballworld.com/volleyball/matches',
    ],
    'tennis': [
        'https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard',
        'https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard',
    ],
    'ufc': [
        'http://ufcstats.com/statistics/events/completed?page=all',
        'https://ufcstats.com/statistics/events/upcoming',
    ],
    'rizin': [
        'https://jp.rizinff.com/',
        'https://jp.rizinff.com/_tags/大会情報',
    ],
    'f1': [
        'https://api.jolpi.ca/ergast/f1/current.json?limit=100',
        'https://api.openf1.org/v1/sessions?year=2026',
    ],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--sport', choices=SPORTS, required=True)
    ap.add_argument('--timeout', type=float, default=float(os.getenv('V45_PROBE_TIMEOUT', '12')))
    a = ap.parse_args()
    headers = {'User-Agent': os.getenv('SPORTS_PIPELINE_USER_AGENT', 'SevenSportResearchEngine/health-probe')}
    rows = []
    for url in SOURCES[a.sport]:
        t0 = time.monotonic()
        try:
            r = requests.get(url, headers=headers, timeout=a.timeout, allow_redirects=True)
            elapsed = round(time.monotonic() - t0, 3)
            ok = 200 <= r.status_code < 400 and bool(r.text)
            rows.append({'url': url, 'status_code': r.status_code, 'bytes': len(r.content), 'elapsed_sec': elapsed, 'ok': ok, 'final_url': r.url})
        except Exception as e:
            rows.append({'url': url, 'ok': False, 'error': repr(e), 'elapsed_sec': round(time.monotonic() - t0, 3)})
    healthy = any(x.get('ok') for x in rows)
    report = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'sport': a.sport, 'healthy': healthy, 'sources': rows}
    out = ROOT / 'results/v45/source_probe'
    out.mkdir(parents=True, exist_ok=True)
    (out / f'{a.sport}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if healthy else 2

if __name__ == '__main__':
    raise SystemExit(main())
