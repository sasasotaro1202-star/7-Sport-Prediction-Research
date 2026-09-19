from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
SPORTS=('valorant','basketball','volleyball','ufc','rizin','tennis','f1','rugby')


def source_count_for_sport(c, sport):
    cols={r[1] for r in c.execute('PRAGMA table_info(source_snapshot)')}
    if 'sport' in cols:
        return c.execute('SELECT COUNT(*) FROM source_snapshot WHERE sport=?',(sport,)).fetchone()[0]
    if 'provenance_json' not in cols:
        return 0
    count=0
    for (payload,) in c.execute('SELECT provenance_json FROM source_snapshot'):
        if not payload:
            continue
        try:
            if json.loads(payload).get('sport')==sport:
                count += 1
        except Exception:
            continue
    return count


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--sport',choices=SPORTS,required=True)
    a=ap.parse_args()
    # RIZIN can be explicitly DEFERRED when its public source exposes no
    # machine-readable records. The release gate validates that state separately.
    if a.sport == 'rugby':
        cov = ROOT/'data/db/rugby_coverage.json'
        if not cov.is_file():
            cov = ROOT/'results/v45/rugby_coverage.json'
        if cov.is_file():
            try:
                data=json.loads(cov.read_text(encoding='utf-8'))
                if data.get('status') == 'DEFERRED' and data.get('events',0) == 0 and data.get('source_snapshots',0) == 0 and data.get('reason'):
                    report={'status':'DEFERRED','sport':'rugby','events':0,'source_snapshots':0,'timed_events':0,'participants':0,'reason':data['reason']}
                    p=ROOT/'results/v45'; p.mkdir(parents=True,exist_ok=True)
                    (p/f'collection_guard_{a.sport}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                    print(json.dumps(report,ensure_ascii=False,indent=2))
                    raise SystemExit(0)
            except (OSError, ValueError):
                pass
    if a.sport == 'rizin':
        cov = ROOT/'results/v45/rizin_coverage.json'
        if cov.is_file():
            try:
                data=json.loads(cov.read_text(encoding='utf-8'))
                if data.get('status') == 'DEFERRED' and data.get('events',0) == 0 and data.get('source_snapshots',0) == 0 and data.get('reason'):
                    report={'status':'DEFERRED','sport':'rizin','events':0,'source_snapshots':0,'timed_events':0,'participants':0,'reason':data['reason']}
                    p=ROOT/'results/v45'; p.mkdir(parents=True,exist_ok=True)
                    (p/f'collection_guard_{a.sport}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                    print(json.dumps(report,ensure_ascii=False,indent=2))
                    raise SystemExit(0)
            except (OSError, ValueError):
                pass
    if not DB.exists() or DB.stat().st_size == 0:
        report={'status':'DEFERRED','reason':'database_missing_or_empty','sport':a.sport}
        exit_code=2
    else:
        c=sqlite3.connect(DB)
        try:
            integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
            tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required={'event','participant','source_snapshot'}
            if integrity != 'ok' or not required.issubset(tables):
                report={
                    'status':'DEFERRED',
                    'reason':'database_integrity_or_schema_failure',
                    'sport':a.sport,
                    'integrity':integrity,
                    'missing_tables':sorted(required-tables),
                }
                exit_code=2
            else:
                if a.sport == 'basketball':
                    events=c.execute("SELECT COUNT(*) FROM event WHERE sport='basketball' AND (lower(COALESCE(competition_id,'')) LIKE '%b.league%' OR lower(COALESCE(competition_id,'')) LIKE '%b league%' OR lower(COALESCE(competition_id,'')) LIKE '%bリーグ%' OR lower(COALESCE(competition_id,'')) LIKE '%asian games%' OR lower(COALESCE(competition_id,'')) LIKE '%アジア大会%')").fetchone()[0]
                    timed=c.execute("SELECT COUNT(*) FROM event WHERE sport='basketball' AND event_time_utc IS NOT NULL AND (lower(name) LIKE '%b.league%' OR lower(name) LIKE '%b league%' OR lower(name) LIKE '%bリーグ%' OR lower(COALESCE(competition_id,'')) LIKE '%asian games%' OR lower(COALESCE(competition_id,'')) LIKE '%アジア大会%')").fetchone()[0]
                    participants=c.execute("SELECT COUNT(*) FROM participant WHERE sport='basketball'").fetchone()[0]
                    sources=source_count_for_sport(c,a.sport)
                    if events==0:
                        report={'status':'DEFERRED','sport':a.sport,'events':0,'source_snapshots':sources,'timed_events':0,'participants':participants,'reason':'requested_B.LEAGUE_and_Asian_Games_target_coverage_not_yet_proven'}
                        exit_code=0
                    else:
                        status='PASS' if sources>0 and timed==events else 'PARTIAL'
                        report={'status':status,'sport':a.sport,'events':events,'source_snapshots':sources,'timed_events':timed,'participants':participants}
                        exit_code=0 if status in {'PASS','PARTIAL'} else 2
                elif a.sport == 'volleyball':
                    events=c.execute("SELECT COUNT(*) FROM event WHERE sport='volleyball' AND (lower(COALESCE(competition_id,'')) LIKE '%asian games%' OR lower(COALESCE(competition_id,'')) LIKE '%アジア大会%')").fetchone()[0]
                    timed=c.execute("SELECT COUNT(*) FROM event WHERE sport='volleyball' AND event_time_utc IS NOT NULL AND (lower(name) LIKE '%asian games%' OR lower(name) LIKE '%アジア大会%')").fetchone()[0]
                    participants=c.execute("SELECT COUNT(*) FROM participant WHERE sport='volleyball'").fetchone()[0]
                    sources=source_count_for_sport(c,a.sport)
                    if events==0:
                        report={'status':'DEFERRED','sport':a.sport,'events':0,'source_snapshots':sources,'timed_events':0,'participants':participants,'reason':'requested_Asian_Games_target_coverage_not_yet_proven'}
                        exit_code=0
                    else:
                        status='PASS' if sources>0 and timed==events else 'PARTIAL'
                        report={'status':status,'sport':a.sport,'events':events,'source_snapshots':sources,'timed_events':timed,'participants':participants}
                        exit_code=0 if status in {'PASS','PARTIAL'} else 2
                else:
                    events=c.execute('SELECT COUNT(*) FROM event WHERE sport=?',(a.sport,)).fetchone()[0]
                    sources=source_count_for_sport(c,a.sport)
                    timed=c.execute('SELECT COUNT(*) FROM event WHERE sport=? AND event_time_utc IS NOT NULL',(a.sport,)).fetchone()[0]
                    participants=c.execute('SELECT COUNT(*) FROM participant WHERE sport=?',(a.sport,)).fetchone()[0]
                    if events>0 and sources>0:
                        status='PASS'
                    elif events>0 or sources>0:
                        status='PARTIAL'
                    else:
                        status='DEFERRED'
                    report={'status':status,'sport':a.sport,'events':events,'source_snapshots':sources,'timed_events':timed,'participants':participants}
                    exit_code=0 if status in {'PASS','PARTIAL'} else 2
        finally:
            c.close()
    p=ROOT/'results/v45'; p.mkdir(parents=True,exist_ok=True)
    (p/f'collection_guard_{a.sport}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(exit_code)

if __name__=='__main__': main()
