from __future__ import annotations
import json, math, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
OUT=ROOT/'results/release_gate.json'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1')

COMPLETED_STATUSES=('COMPLETED','FINISHED','POST')


def _finite(x):
    try:
        return math.isfinite(float(x))
    except Exception:
        return False


def _validate_model(meta):
    required=('model_version','feature_version','training_cutoff_utc','git_commit_sha','artifact_path')
    missing=[k for k in required if not meta.get(k)]
    if missing:
        return False, f'model_metadata_missing:{",".join(missing)}'
    if meta.get('holdout_frozen') is not True:
        return False, 'holdout_not_frozen'
    if meta.get('production_fit_excludes_holdout') is not True:
        return False, 'production_fit_includes_holdout_or_unproven'
    hm=meta.get('holdout_metrics') or {}
    for k in ('logloss','brier','accuracy','ece','n'):
        if not _finite(hm.get(k)):
            return False, f'holdout_metric_invalid:{k}'
    if float(hm['n']) < 30:
        return False, 'holdout_sample_too_small'
    if float(hm['ece']) > 0.20:
        return False, 'holdout_calibration_failed'
    return True, 'OK'


def main():
    r={
        'status':'BLOCKED',
        'publish':False,
        'fatal':[],
        'coverage':{},
        'policy':'source outages may degrade coverage, but unsafe models are never published; future scheduled events do not require outcomes',
        'gate_version':'release-gate-v3-completed-outcomes-only',
    }
    if not DB.exists():
        r['fatal'].append('database_missing')
    else:
        c=sqlite3.connect(DB)
        try:
            counts=dict(c.execute('select sport,count(*) from event group by sport').fetchall())
            timed=dict(c.execute('select sport,count(*) from event where event_time_utc is not null group by sport').fetchall())
            completed=dict(c.execute("select sport,count(*) from event where status in ('COMPLETED','FINISHED','POST') group by sport").fetchall())
            verified=dict(c.execute("select sport,count(*) from event_outcome where outcome_status='VERIFIED' and outcome in ('A','B','DRAW') group by sport").fetchall())
            models=dict(c.execute("select sport,count(*) from model_state_snapshot where quality_status like 'ACCEPTED%' group by sport").fetchall())
            model_rows=c.execute("select sport,metadata_json from model_state_snapshot where market='winner' and quality_status like 'ACCEPTED%' order by as_of_utc desc").fetchall()
            bad=c.execute("select count(*) from pit_replay where leakage_status not in ('PASS','UNKNOWN','CLEAN')").fetchone()[0]
            exact_missing=c.execute("select count(*) from source_snapshot where availability_status='EXACT' and source_available_at_utc is null").fetchone()[0]
            r['coverage']={s:{'events':int(counts.get(s,0)),'timed_events':int(timed.get(s,0)),'completed_events':int(completed.get(s,0)),'verified_outcomes':int(verified.get(s,0)),'accepted_models':int(models.get(s,0))} for s in SPORTS}
            latest={}
            for sport,payload in model_rows:
                if sport in latest: continue
                try: latest[sport]=json.loads(payload or '{}')
                except Exception: latest[sport]={}
            for s in SPORTS:
                if s not in latest:
                    continue
                ok,reason=_validate_model(latest[s])
                r['coverage'][s]['model_safety']=reason
                if not ok:
                    r['fatal'].append(f'{s}:{reason}')
            if bad:
                r['fatal'].append('pit_leakage_detected')
            if exact_missing:
                r['fatal'].append('exact_source_missing_availability_time')
            for s,v in r['coverage'].items():
                if v['events'] and v['timed_events'] != v['events']:
                    r['fatal'].append(f'{s}:untimed_events_present')
                # Only historical/completed events require an outcome. Scheduled/upcoming
                # events are valid production candidates and must not poison the release gate.
                if v['completed_events'] and v['verified_outcomes'] < v['completed_events']:
                    r['fatal'].append(f'{s}:completed_event_outcome_gap')
        finally:
            c.close()
    if not r['fatal']:
        ready=all(v['events']>0 and v['accepted_models']>0 and v.get('model_safety')=='OK' for v in r['coverage'].values())
        r['status']='READY' if ready else 'DEGRADED_BLOCKED'
        r['publish']=ready
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(r,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
