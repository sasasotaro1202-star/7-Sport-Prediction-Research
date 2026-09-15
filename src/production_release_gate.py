from __future__ import annotations
import json, math, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
OUT=ROOT/'results/release_gate.json'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1')

COMPLETED_STATUSES=('COMPLETED','FINISHED','POST')
RESOLVED_OUTCOMES=('A','B','DRAW','VOID')
MODEL_OUTCOMES=('A','B','DRAW')


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


def _f1_resolved_counts(c):
    """F1 is a multi-entrant classification problem; event_outcome A/B is
    intentionally not used to represent a race winner. Resolve a completed
    race from source-backed results.position == 1 instead."""
    rows=c.execute("""
        SELECT e.event_id
        FROM event e
        WHERE e.sport='f1' AND e.status IN ('COMPLETED','FINISHED','POST')
    """).fetchall()
    resolved=0
    for (eid,) in rows:
        n=c.execute("""
            SELECT COUNT(*) FROM match_stats
            WHERE event_id=? AND sport='f1'
              AND stat_name='results.position'
              AND value_num=1
              AND source IS NOT NULL
        """,(eid,)).fetchone()[0]
        if n>0:
            resolved+=1
    return len(rows),resolved


def main():
    r={
        'status':'BLOCKED',
        'publish':False,
        'fatal':[],
        'coverage':{},
        'policy':'source outages may degrade coverage, but unsafe models are never published; future scheduled events do not require outcomes; explicit VOID results are resolved but excluded from model labels; F1 race winners are validated from source-backed finishing positions rather than the binary A/B outcome schema',
        'gate_version':'release-gate-v5-sport-aware-outcome-validation',
    }
    if not DB.exists():
        r['fatal'].append('database_missing')
    else:
        c=sqlite3.connect(DB)
        try:
            counts=dict(c.execute('select sport,count(*) from event group by sport').fetchall())
            timed=dict(c.execute('select sport,count(*) from event where event_time_utc is not null group by sport').fetchall())
            completed=dict(c.execute("select sport,count(*) from event where status in ('COMPLETED','FINISHED','POST') group by sport").fetchall())
            resolved=dict(c.execute("select sport,count(*) from event_outcome where outcome_status='VERIFIED' and outcome in ('A','B','DRAW','VOID') group by sport").fetchall())
            verified=dict(c.execute("select sport,count(*) from event_outcome where outcome_status='VERIFIED' and outcome in ('A','B','DRAW') group by sport").fetchall())
            models=dict(c.execute("select sport,count(*) from model_state_snapshot where quality_status like 'ACCEPTED%' group by sport").fetchall())
            model_rows=c.execute("select sport,metadata_json from model_state_snapshot where market='winner' and quality_status like 'ACCEPTED%' order by as_of_utc desc").fetchall()
            bad=c.execute("select count(*) from pit_replay where leakage_status not in ('PASS','UNKNOWN','CLEAN')").fetchone()[0]
            exact_missing=c.execute("select count(*) from source_snapshot where availability_status='EXACT' and source_available_at_utc is null").fetchone()[0]
            r['coverage']={s:{'events':int(counts.get(s,0)),'timed_events':int(timed.get(s,0)),'completed_events':int(completed.get(s,0)),'resolved_outcomes':int(resolved.get(s,0)),'verified_model_outcomes':int(verified.get(s,0)),'accepted_models':int(models.get(s,0))} for s in SPORTS}

            # F1 is multi-entrant and must not be coerced into A/B. Replace
            # the generic event_outcome resolution count with verified race
            # winners from source-backed finishing positions.
            f1_completed,f1_resolved=_f1_resolved_counts(c)
            r['coverage']['f1']['resolved_outcomes']=f1_resolved
            r['coverage']['f1']['verified_model_outcomes']=0
            r['coverage']['f1']['outcome_semantics']='multi_entrant_winner_from_results_position'

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
                # F1 uses sport-aware multi-entrant winner resolution above;
                # all other sports use the binary/void event_outcome contract.
                if s=='f1':
                    if v['completed_events'] and v['resolved_outcomes'] < v['completed_events']:
                        r['fatal'].append(f'{s}:completed_event_outcome_gap')
                elif v['completed_events'] and v['resolved_outcomes'] < v['completed_events']:
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
