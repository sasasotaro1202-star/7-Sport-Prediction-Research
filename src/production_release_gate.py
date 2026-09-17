from __future__ import annotations
import json, math, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
OUT=ROOT/'results/release_gate.json'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1')
COMPLETED_STATUSES=('COMPLETED','FINISHED','POST')


def _finite(x):
    try: return math.isfinite(float(x))
    except Exception: return False


def _validate_model(meta):
    required=('model_version','feature_version','training_cutoff_utc','git_commit_sha','artifact_path')
    missing=[k for k in required if not meta.get(k)]
    if missing: return False, f'model_metadata_missing:{",".join(missing)}'
    if meta.get('holdout_frozen') is not True: return False, 'holdout_not_frozen'
    if meta.get('production_fit_excludes_holdout') is not True: return False, 'production_fit_includes_holdout_or_unproven'
    hm=meta.get('holdout_metrics') or {}
    for k in ('logloss','brier','accuracy','ece','n'):
        if not _finite(hm.get(k)): return False, f'holdout_metric_invalid:{k}'
    if float(hm['n']) < 30: return False, 'holdout_sample_too_small'
    if float(hm['ece']) > 0.20: return False, 'holdout_calibration_failed'
    return True, 'OK'


def _f1_resolved_counts(c):
    rows=c.execute("SELECT event_id FROM event WHERE sport='f1' AND status IN ('COMPLETED','FINISHED','POST')").fetchall()
    resolved=0
    for (eid,) in rows:
        n=c.execute("SELECT COUNT(*) FROM match_stats WHERE event_id=? AND sport='f1' AND stat_name='results.position' AND value_num=1 AND source IS NOT NULL",(eid,)).fetchone()[0]
        if n>0: resolved += 1
    return len(rows), resolved


def _write(r):
    if not r['fatal']:
        r['status']='READY'; r['publish']=True
    else:
        r['status']='BLOCKED'; r['publish']=False
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(r,ensure_ascii=False,indent=2))
    # BLOCKED is intentionally a non-zero process result. The release gate must not
    # make an unsafe or incomplete release appear as a successful GitHub Action.
    return 0 if not r['fatal'] else 1


def main():
    r={'status':'BLOCKED','publish':False,'fatal':[],'coverage':{},'policy':'source outages may degrade coverage, but unsafe or unverified models are never published; future scheduled events do not require outcomes; explicit VOID results are resolved but excluded from model labels; F1 uses source-backed finishing positions rather than binary A/B outcomes','gate_version':'release-gate-v7-visible-blocked'}
    if not DB.exists():
        r['fatal'].append('database_missing')
        return _write(r)
    c=sqlite3.connect(DB)
    try:
        ok=c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        required=('event','participant','event_participant','source_snapshot','event_outcome','model_state_snapshot')
        existing={x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        missing_tables=[x for x in required if x not in existing]
        if not ok: r['fatal'].append('database_integrity_failed')
        if missing_tables: r['fatal'].append('database_schema_missing:'+','.join(missing_tables))
        if r['fatal']: return _write(r)
        counts=dict(c.execute('SELECT sport,count(*) FROM event GROUP BY sport').fetchall())
        timed=dict(c.execute('SELECT sport,count(*) FROM event WHERE event_time_utc IS NOT NULL GROUP BY sport').fetchall())
        completed=dict(c.execute("SELECT sport,count(*) FROM event WHERE status IN ('COMPLETED','FINISHED','POST') GROUP BY sport").fetchall())
        resolved=dict(c.execute("SELECT sport,count(*) FROM event_outcome WHERE outcome_status='VERIFIED' AND outcome IN ('A','B','DRAW','VOID') GROUP BY sport").fetchall())
        verified=dict(c.execute("SELECT sport,count(*) FROM event_outcome WHERE outcome_status='VERIFIED' AND outcome IN ('A','B','DRAW') GROUP BY sport").fetchall())
        models=dict(c.execute("SELECT sport,count(*) FROM model_state_snapshot WHERE quality_status LIKE 'ACCEPTED%' GROUP BY sport").fetchall())
        model_rows=c.execute("SELECT sport,metadata_json FROM model_state_snapshot WHERE market='winner' AND quality_status LIKE 'ACCEPTED%' ORDER BY as_of_utc DESC").fetchall()
        latest={}
        for sport,payload in model_rows:
            if sport not in latest:
                try: latest[sport]=json.loads(payload or '{}')
                except Exception: latest[sport]={}
        r['coverage']={s:{'events':int(counts.get(s,0)),'timed_events':int(timed.get(s,0)),'completed_events':int(completed.get(s,0)),'resolved_outcomes':int(resolved.get(s,0)),'verified_model_outcomes':int(verified.get(s,0)),'accepted_models':int(models.get(s,0))} for s in SPORTS}
        f1_completed,f1_resolved=_f1_resolved_counts(c)
        r['coverage']['f1'].update({'completed_events':f1_completed,'resolved_outcomes':f1_resolved,'verified_model_outcomes':0,'outcome_semantics':'multi_entrant_winner_from_results_position'})
        for s in SPORTS:
            if s in latest:
                good,reason=_validate_model(latest[s]); r['coverage'][s]['model_safety']=reason
                if not good: r['fatal'].append(f'{s}:{reason}')
            else:
                r['fatal'].append(f'{s}:accepted_model_missing')
            v=r['coverage'][s]
            if v['events']==0: r['fatal'].append(f'{s}:no_events')
            elif v['timed_events']!=v['events']: r['fatal'].append(f'{s}:untimed_events_present')
            if v['completed_events'] and v['resolved_outcomes']<v['completed_events']:
                r['fatal'].append(f'{s}:completed_event_outcome_gap')
        bad=c.execute("SELECT COUNT(*) FROM pit_replay WHERE leakage_status NOT IN ('PASS','UNKNOWN','CLEAN')").fetchone()[0]
        if bad: r['fatal'].append('pit_leakage_detected')
        exact_missing=c.execute("SELECT COUNT(*) FROM source_snapshot WHERE availability_status='EXACT' AND source_available_at_utc IS NULL").fetchone()[0]
        if exact_missing: r['fatal'].append('exact_source_missing_availability_time')
    finally:
        c.close()
    return _write(r)


if __name__=='__main__': raise SystemExit(main())
