from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--sport',choices=SPORTS,required=True)
    a=ap.parse_args()
    if not DB.exists():
        print(json.dumps({'status':'FAIL','reason':'database_missing','sport':a.sport}))
        raise SystemExit(2)
    c=sqlite3.connect(DB)
    q=lambda t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    events=c.execute('SELECT COUNT(*) FROM event WHERE sport=?',(a.sport,)).fetchone()[0]
    sources=c.execute('SELECT COUNT(*) FROM source_snapshot WHERE sport=?',(a.sport,)).fetchone()[0]
    timed=c.execute('SELECT COUNT(*) FROM event WHERE sport=? AND event_time_utc IS NOT NULL',(a.sport,)).fetchone()[0]
    participants=c.execute('SELECT COUNT(*) FROM participant WHERE sport=?',(a.sport,)).fetchone()[0]
    report={'status':'PASS' if events>0 and sources>0 else 'NO_DATA','sport':a.sport,'events':events,'source_snapshots':sources,'timed_events':timed,'participants':participants,'total_db_events':q('event')}
    c.close()
    p=ROOT/'results/v45'; p.mkdir(parents=True,exist_ok=True); (p/f'collection_guard_{a.sport}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if report['status']=='PASS' else 2)
if __name__=='__main__': main()
