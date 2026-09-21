from __future__ import annotations
import argparse,json,math,sqlite3
from datetime import datetime,timezone
from pathlib import Path
import joblib,numpy as np
from src import dynamic_model_router as router
from src import research_cycle_v4 as base

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
MODELS=ROOT/'models/research'
OUT=ROOT/'results/future_predictions.json'
SPORTS=tuple(base.SPORTS)
PIT_LEAD_MINUTES=60


def utc_now():
    return datetime.now(timezone.utc)


def _apply_calibration(p, calibrator, method):
    p=np.clip(np.asarray(p,dtype=float),1e-6,1-1e-6)
    if calibrator is None:
        return p
    if method=='sigmoid':
        z=np.log(p/(1.0-p)).reshape(-1,1)
        return np.clip(calibrator.predict_proba(z)[:,1],1e-6,1-1e-6)
    if method=='beta':
        z=np.column_stack([np.log(p),np.log(1.0-p)])
        return np.clip(calibrator.predict_proba(z)[:,1],1e-6,1-1e-6)
    if method=='isotonic':
        return np.clip(calibrator.predict(p),1e-6,1-1e-6)
    return p


def _future_events(c,s,now):
    return {
        row[0]: {'event_id':row[0],'event_time_utc':row[1],'status':row[2],
                 'participant_count':int(row[3] or 0)}
        for row in c.execute(
            """SELECT e.event_id,e.event_time_utc,e.status,
                      (SELECT COUNT(DISTINCT ep.participant_id)
                         FROM event_participant ep
                        WHERE ep.event_id=e.event_id
                          AND ep.participant_id IS NOT NULL)
                 FROM event e
                WHERE e.sport=?
                  AND e.event_time_utc IS NOT NULL
                ORDER BY e.event_time_utc,e.event_id""",(s,)
        ).fetchall()
        if row[1] and _after_cutoff(row[1],now,PIT_LEAD_MINUTES)
        and str(row[2] or '').upper() not in {'COMPLETED','FINISHED','POST','FINAL','CANCELLED','VOID'}
    }


def _after_cutoff(ts,now,lead_minutes):
    try:
        dt=datetime.fromisoformat(str(ts).replace('Z','+00:00'))
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        return dt > now and (dt-now).total_seconds() >= float(lead_minutes)*60.0
    except Exception:
        return False

def _after_now(ts,now):
    try:
        dt=datetime.fromisoformat(str(ts).replace('Z','+00:00'))
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        return dt>now
    except Exception:
        return False


def predict_sport(c,s,now):
    artifact_path=MODELS/f'{s}_current.joblib'
    if not artifact_path.is_file() or artifact_path.stat().st_size<=0:
        return {'sport':s,'status':'DEFERRED_NO_ACCEPTED_ARTIFACT'}
    try:
        artifact=joblib.load(artifact_path)
    except Exception as exc:
        return {'sport':s,'status':'BLOCKED_ARTIFACT_LOAD','reason':type(exc).__name__}
    if artifact.get('quality_status') not in ('ACCEPTED_LOCKED_HOLDOUT','ACCEPTED_AFTER_LOCKED_HOLDOUT'):
        return {'sport':s,'status':'DEFERRED_ARTIFACT_NOT_ACCEPTED','quality_status':artifact.get('quality_status')}
    features=list(artifact.get('features') or [])
    models=list(artifact.get('models') or [])
    names=list(artifact.get('model_names') or [])
    weights=artifact.get('ensemble_weights') or {}
    if not features or not models or not names or len(models)!=len(names):
        return {'sport':s,'status':'BLOCKED_ARTIFACT_SCHEMA'}
    router_status=str(artifact.get('dynamic_router_status') or 'FALLBACK_FIXED_ENSEMBLE')
    router_obj=artifact.get('dynamic_router')
    if router_status=='PRODUCTION_ROUTABLE_AFTER_GATES' and router_obj is None:
        return {'sport':s,'status':'BLOCKED_ARTIFACT_ROUTER_STATE'}
    rows,_=base.build(c,s,include_unlabeled=True)
    future=_future_events(c,s,now)
    outputs=[]
    router_status=str(artifact.get('dynamic_router_status') or 'FALLBACK_FIXED_ENSEMBLE')
    use_router=router_status=='PRODUCTION_ROUTABLE_AFTER_GATES' and artifact.get('dynamic_router') is not None
    rnames=list(artifact.get('dynamic_router_names') or [])
    rmodels=artifact.get('dynamic_router_models') or {}
    rref=artifact.get('dynamic_router_feature_reference') if artifact.get('dynamic_router_feature_reference') is not None else None
    cal=artifact.get('probability_calibrator')
    cal_method=str((artifact.get('probability_calibration') or {}).get('method') or 'none')
    model_map={n:m for n,m in zip(names,models)}
    for eid,t,label,row_features in rows:
        meta=future.get(eid)
        if meta is None:
            continue
        if meta['participant_count']!=2:
            continue
        x=np.asarray([[row_features.get(f,np.nan) for f in features]],dtype=float)
        if use_router and rref is not None and rnames and all(n in rmodels for n in rnames):
            rbase=[rmodels[n] for n in rnames]
            raw,_=router.predict_with_router(artifact['dynamic_router'],rbase,rnames,rref,x)
            strategy='contextual_router'
        else:
            preds=[]
            for n,m in zip(names,models):
                preds.append(float(np.clip(m.predict_proba(x)[0,1],1e-6,1-1e-6)))
            pweights=[float(weights.get(n,1.0/len(names))) for n in names]
            z=sum(p*w for p,w in zip(preds,pweights))
            total=sum(pweights)
            raw=np.asarray([z/max(total,1e-12)],dtype=float)
            strategy=str(artifact.get('ensemble_strategy') or 'fixed_equal_weight')
        # The stored outer calibrator was trained for the selected fixed/weighted
        # ensemble. Never apply it to a different Router output distribution.
        apply_cal = None if strategy=='contextual_router' else cal
        apply_method = 'none' if strategy=='contextual_router' else cal_method
        p=float(_apply_calibration(raw,apply_cal,apply_method)[0])
        a,b=c.execute(
            """SELECT GROUP_CONCAT(CASE WHEN side='A' THEN canonical_name END),
                      GROUP_CONCAT(CASE WHEN side='B' THEN canonical_name END)
                 FROM event_participant ep
                 LEFT JOIN participant p ON p.participant_id=ep.participant_id
                WHERE ep.event_id=?""",(eid,)).fetchone()
        outputs.append({
            'event_id':eid,'event_time_utc':t,'prediction_cutoff_at_utc':(datetime.fromisoformat(str(t).replace('Z','+00:00'))-__import__('datetime').timedelta(minutes=PIT_LEAD_MINUTES)).isoformat(),'side_a':a,'side_b':b,
            'probability_side_b':p,'probability_side_a':1.0-p,
            'strategy':strategy,'router_status':router_status,
            'models':list(names) if strategy!='contextual_router' else list(rnames),
            'ensemble_weights':dict(weights) if strategy!='contextual_router' else None,
            'model_version':artifact.get('model_version'),
            'feature_version':artifact.get('feature_version') or 'unknown',
            'generated_at_utc':now.isoformat(),
        })
    return {'sport':s,'status':'PREDICTED' if outputs else 'NO_FUTURE_EVENTS',
            'predictions':outputs,'count':len(outputs)}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--sport',choices=SPORTS);args=ap.parse_args()
    now=utc_now()
    con=sqlite3.connect(DB)
    try:
        sports=[args.sport] if args.sport else list(SPORTS)
        results=[predict_sport(con,s,now) for s in sports]
    finally:
        con.close()
    report={'generated_at_utc':now.isoformat(),'policy':'accepted-artifact-only; PIT-safe research features; gated contextual routing; frozen-holdout-validated calibration','sports':results}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    blocked=[r for r in results if str(r.get('status','')).startswith('BLOCKED_')]
    return 1 if blocked else 0


if __name__=='__main__':
    raise SystemExit(main())
