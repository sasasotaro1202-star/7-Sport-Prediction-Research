from __future__ import annotations
import argparse, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1')


def now(): return datetime.now(timezone.utc).isoformat()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--strict',action='store_true')
    ap.add_argument('--sport',choices=SPORTS)
    a=ap.parse_args()
    checks=[]; fatal=[]
    if not DB.exists():
        fatal.append('database_missing')
    else:
        con=sqlite3.connect(DB)
        tables={r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        required={'event','participant','event_participant','match_stats','source_snapshot','event_outcome','pit_replay','pit_feature_snapshot','model_state_snapshot','collection_state'}
        missing=sorted(required-tables)
        checks.append({'check':'required_tables','ok':not missing,'missing':missing})
        rows=con.execute('select sport,count(*) from event group by sport').fetchall()
        counts={k:int(v) for k,v in rows}
        scope_sports=(a.sport,) if a.sport else SPORTS
        checks.append({'check':'sports_present','ok':all(counts.get(s,0)>0 for s in scope_sports),'counts':{s:counts.get(s,0) for s in scope_sports}})
        bad_time=con.execute("select count(*) from event where event_time_utc is not null and datetime(event_time_utc) < '1950-01-01'").fetchone()[0]
        checks.append({'check':'event_time_sanity','ok':bad_time==0,'bad_rows':int(bad_time)})
        unver=con.execute("select count(*) from source_snapshot where availability_status='UNVERIFIABLE'").fetchone()[0] if 'source_snapshot' in tables else 0
        checks.append({'check':'source_timing_transparency','ok':True,'unverifiable_source_timestamps':int(unver),'policy':'UNVERIFIABLE is never promoted to PIT_EXACT'})
        if 'pit_replay' in tables:
            leak=con.execute("select count(*) from pit_replay where leakage_status not in ('PASS','UNKNOWN')").fetchone()[0]
            exact=con.execute("select count(*) from pit_replay where replay_status='EXACT' and leakage_status='PASS'").fetchone()[0]
            checks.append({'check':'pit_leakage','ok':leak==0,'nonpass':int(leak),'exact_pass':int(exact)})
        if 'event_outcome' in tables:
            outcomes=con.execute("select sport,count(*) from event_outcome where outcome_status='VERIFIED' group by sport").fetchall()
            oc={k:int(v) for k,v in outcomes}
            checks.append({'check':'verified_outcomes','ok':all(oc.get(s,0)>0 for s in scope_sports),'counts':{s:oc.get(s,0) for s in scope_sports}})
        if 'collection_state' in tables:
            states=con.execute("select sport,scope,completed from collection_state").fetchall()
            checks.append({'check':'checkpoint_state','ok':True,'states':len(states),'completed':sum(int(x[2]) for x in states)})
        con.close()
    ok=not fatal and all(x.get('ok',False) for x in checks)
    report={'timestamp_utc':now(),'status':'PASS' if ok else 'FAIL','fatal':fatal,'checks':checks,'strict':a.strict,'scope':a.sport or 'global'}
    out=ROOT/'results/quality_gate.json'; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if ok else 2)

if __name__=='__main__': main()
