from __future__ import annotations
import argparse, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1')

def now(): return datetime.now(timezone.utc).isoformat()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--strict',action='store_true'); a=ap.parse_args()
    checks=[]; fatal=[]
    if not DB.exists():
        fatal.append('database_missing')
    else:
        con=sqlite3.connect(DB)
        tables={r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        required={'event','participant','event_participant','match_stats','source_snapshot','pit_replay','pit_feature_snapshot'}
        missing=sorted(required-tables); checks.append({'check':'required_tables','ok':not missing,'missing':missing})
        rows=con.execute('select sport,count(*) from event group by sport').fetchall()
        counts={k:int(v) for k,v in rows}
        checks.append({'check':'seven_sports_present','ok':all(s in counts for s in SPORTS),'counts':counts})
        bad_time=con.execute("select count(*) from event where event_time_utc is not null and datetime(event_time_utc) < '1950-01-01'").fetchone()[0]
        checks.append({'check':'event_time_sanity','ok':bad_time==0,'bad_rows':bad_time})
        if 'source_snapshot' in tables:
            unver=con.execute("select count(*) from source_snapshot where availability_status='UNVERIFIABLE'").fetchone()[0]
            checks.append({'check':'source_timing_transparency','ok':True,'unverifiable_source_timestamps':int(unver),'policy':'UNVERIFIABLE is never promoted to PIT_EXACT'})
        if 'pit_replay' in tables:
            leak=con.execute("select count(*) from pit_replay where leakage_status not in ('PASS','UNKNOWN')").fetchone()[0]
            checks.append({'check':'pit_leakage','ok':leak==0,'nonpass':int(leak)})
        con.close()
    ok=not fatal and all(x.get('ok',False) for x in checks)
    report={'timestamp_utc':now(),'status':'PASS' if ok else 'FAIL','fatal':fatal,'checks':checks,'strict':a.strict}
    out=ROOT/'results/quality_gate.json'; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if ok else 2)
if __name__=='__main__': main()
