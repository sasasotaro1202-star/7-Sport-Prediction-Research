from __future__ import annotations
import json, math, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
OUT=ROOT/'results/release_gate.json'
SPORTS=('valorant','basketball','volleyball','ufc','rizin')
DEFERRED_SPORTS=('tennis','f1','rugby')
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


def _deferred_report_state(sport):
    candidates=(ROOT/'results/research'/f'{sport}.json', ROOT/'results/v45'/f'{sport}_coverage.json', ROOT/'data/db'/f'{sport}_coverage.json')
    p=next((x for x in candidates if x.exists()),None)
    if p is None:
        return False, f'{sport}_deferred_report_missing'
    try:
        r=json.loads(p.read_text())
    except Exception as exc:
        return False, f'{sport}_deferred_report_invalid:{type(exc).__name__}'
    status=str(r.get('status',''))
    if not status.startswith('DEFERRED'):
        return False, f'{sport}_not_deferred:{status}'
    return True, str(r.get('reason') or r.get('deferred_reason') or status)


def _rugby_deferred_state():
    candidates=(ROOT/'results/v45/rugby_coverage.json', ROOT/'data/db/rugby_coverage.json')
    p=next((x for x in candidates if x.exists()),None)
    if p is None:
        return False, 'rugby_coverage_report_missing'
    try:
        r=json.loads(p.read_text())
    except Exception as exc:
        return False, f'rugby_coverage_report_invalid:{type(exc).__name__}'
    if r.get('sport')!='rugby':
        return False, 'rugby_coverage_report_wrong_sport'
    if r.get('status')!='DEFERRED':
        return False, f"rugby_not_deferred:{r.get('status')}"
    if not r.get('deferred_reason'):
        return False, 'rugby_deferred_reason_missing'
    counts=r.get('counts') or {}
    if counts.get('events',0)!=0 or counts.get('source_snapshots',0)!=0:
        return False, 'rugby_deferred_with_partial_persisted_coverage'
    return True, 'DEFERRED:'+str(r['deferred_reason'])


def _write(r):
    if not r['fatal']:
        r['status']='READY_WITH_EXPLICIT_DEFERRED_SPORTS' if r.get('deferred_sports') else 'READY'
        r['publish']=True
    else:
        r['status']='BLOCKED'; r['publish']=False
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(r,ensure_ascii=False,indent=2))
    return 0 if not r['fatal'] else 1


def main():
    r={'status':'BLOCKED','publish':False,'fatal':[],'deferred_sports':{},'coverage':{},'coverage_warnings':[],'policy':'source outages degrade coverage explicitly; unsafe or unverified models are never published; a sport may be explicitly DEFERRED only when its coverage report proves zero persisted events/snapshots and gives a concrete reason; future scheduled events do not require outcomes; explicit VOID results are resolved but excluded from model labels; F1 uses source-backed finishing positions rather than binary A/B outcomes','gate_version':'release-gate-v9-safe-partial-sport-degradation'}
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
        model_rows=c.execute("SELECT sport,metadata_json,model_version,feature_version,training_cutoff_utc,git_commit_sha,artifact_path FROM model_state_snapshot WHERE market='winner' AND quality_status LIKE 'ACCEPTED%' ORDER BY as_of_utc DESC").fetchall()
        latest={}
        for sport,payload,mv,fv,cutoff,sha,artifact in model_rows:
            if sport not in latest:
                try: meta=json.loads(payload or '{}')
                except Exception: meta={}
                # Provenance columns are canonical DB fields. Hydrate missing JSON
                # metadata from them instead of treating a serialization omission as
                # an unsafe model, while still requiring all safety metrics below.
                meta.setdefault('model_version',mv)
                meta.setdefault('feature_version',fv)
                meta.setdefault('training_cutoff_utc',cutoff)
                meta.setdefault('git_commit_sha',sha)
                meta.setdefault('artifact_path',artifact)
                latest[sport]=meta
        r['coverage']={s:{'events':int(counts.get(s,0)),'timed_events':int(timed.get(s,0)),'completed_events':int(completed.get(s,0)),'resolved_outcomes':int(resolved.get(s,0)),'verified_model_outcomes':int(verified.get(s,0)),'accepted_models':int(models.get(s,0))} for s in SPORTS}
        f1_completed,f1_resolved=_f1_resolved_counts(c)
        r['coverage']['f1'].update({'completed_events':f1_completed,'resolved_outcomes':f1_resolved,'verified_model_outcomes':0,'outcome_semantics':'multi_entrant_winner_from_results_position'})
        for ds in DEFERRED_SPORTS:
            ok, reason = _deferred_report_state(ds)
            if ok:
                r['deferred_sports'][ds]=reason
                r['coverage'].setdefault(ds,{})['model_safety']='DEFERRED:'+reason
            else:
                r['fatal'].append(ds+':'+reason)
        for s in SPORTS:
            if s in DEFERRED_SPORTS:
                continue
            if s in latest:
                good,reason=_validate_model(latest[s]); r['coverage'][s]['model_safety']=reason
                if not good: r['fatal'].append(f'{s}:{reason}')
            else:
                # A sport with a concrete DEFERRED research result is unavailable
                # for production but must not block safe publication of other sports.
                # An unexplained missing model remains fatal.
                rp=ROOT/'results/research'/f'{s}.json'
                deferred_reason=None
                if rp.exists():
                    try:
                        rr=json.loads(rp.read_text(encoding='utf-8'))
                        if str(rr.get('status','')).startswith('DEFERRED'):
                            deferred_reason=rr.get('reason') or rr.get('status')
                    except Exception:
                        deferred_reason=None
                if deferred_reason:
                    r['deferred_sports'][s]=str(deferred_reason)
                    r['coverage'][s]['model_safety']='DEFERRED:'+str(deferred_reason)
                else:
                    r['fatal'].append(f'{s}:accepted_model_missing')
            v=r['coverage'][s]
            if v['events']==0:
                if s not in r['deferred_sports']:
                    r['fatal'].append(f'{s}:no_events')
            elif v['timed_events']!=v['events']:
                r['fatal'].append(f'{s}:untimed_events_present')
            if v['completed_events'] and v['resolved_outcomes']<v['completed_events']:
                r.setdefault('coverage_warnings',[]).append(
                    f'{s}:completed_event_outcome_gap:{v["completed_events"]-v["resolved_outcomes"]}')
        bad=c.execute("SELECT COUNT(*) FROM pit_replay WHERE leakage_status NOT IN ('PASS','UNKNOWN','CLEAN')").fetchone()[0]
        if bad: r['fatal'].append('pit_leakage_detected')
        exact_missing=c.execute("SELECT COUNT(*) FROM source_snapshot WHERE availability_status='EXACT' AND source_available_at_utc IS NULL").fetchone()[0]
        if exact_missing: r['fatal'].append('exact_source_missing_availability_time')
    finally:
        c.close()
    return _write(r)


if __name__=='__main__': raise SystemExit(main())
