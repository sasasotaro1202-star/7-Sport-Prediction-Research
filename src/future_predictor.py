from __future__ import annotations
import argparse,hashlib,json,math,sqlite3
from datetime import datetime,timezone
from pathlib import Path
import joblib,numpy as np
from src import dynamic_model_router as router
from src import matchday_intelligence_oos as matchday_intelligence
from src import research_cycle_v4 as base
from src import prediction_experience as experience

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
MODELS=ROOT/'models/research'
OUT=ROOT/'results/future_predictions.json'
ELIGIBILITY_OUT=ROOT/'results/prediction_eligibility.json'
SPORTS=("valorant","basketball","volleyball","tennis","ufc","rizin","f1","rugby","boxing")
HEAD_TO_HEAD_SPORTS=("valorant","basketball","volleyball","tennis","ufc","rizin","rugby","boxing")
MULTICLASS_SPORTS=("f1",)
PIT_LEAD_MINUTES=60
F1_CURRENT_ROSTER_URL="https://www.formula1.com/en/drivers"

_F1_ROSTER_CACHE=None


def _current_f1_roster(now):
    """Fetch the current official F1 driver roster for future inference only.

    The roster is current-state information, not event-specific entry confirmation.
    It is admitted only when retrieval_time <= the event PIT cutoff, and callers must
    keep the resulting field explicitly low-confidence / unconfirmed.
    """
    global _F1_ROSTER_CACHE
    if _F1_ROSTER_CACHE is not None:
        return _F1_ROSTER_CACHE
    try:
        from urllib.request import Request,urlopen
        from bs4 import BeautifulSoup
        req=Request(
            F1_CURRENT_ROSTER_URL,
            headers={"User-Agent":"SevenSportResearchEngine/F1-Future-Roster","Accept-Language":"en-US,en;q=0.8"},
        )
        with urlopen(req,timeout=15) as r:
            raw=r.read().decode("utf-8","ignore")
        retrieved=utc_now()
        soup=BeautifulSoup(raw,"lxml")
        names=[]
        for a in soup.select('a[href*="/en/drivers/"]'):
            href=str(a.get("href") or "")
            text_name=" ".join(a.get_text(" ",strip=True).split())
            if not text_name or href.rstrip("/").endswith("/drivers"):
                continue
            slug=href.rstrip("/").split("/")[-1]
            if not slug or slug in {"drivers"}:
                continue
            name=" ".join(part.capitalize() for part in slug.replace("-"," ").split())
            if len(name.split()) < 2:
                continue
            if name not in names:
                names.append(name)
        names=names[:30]
        _F1_ROSTER_CACHE=(retrieved,names)
    except Exception:
        _F1_ROSTER_CACHE=None
    return _F1_ROSTER_CACHE

DEDICATED_DBS={
    'rugby': ROOT/'data/db/rugby_v45.sqlite',
    'boxing': ROOT/'data/db/boxing_v45.sqlite',
}


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


def _prediction_id(event_id, model_version, cutoff):
    return hashlib.sha256(f"future-v1|{event_id}|winner|{model_version}|{cutoff}".encode()).hexdigest()[:32]

def _participant_sides(c,event_id):
    rows=c.execute(
        """SELECT ep.side,ep.participant_id,p.canonical_name
             FROM event_participant ep
             LEFT JOIN participant p ON p.participant_id=ep.participant_id
            WHERE ep.event_id=? AND ep.side IN ('A','B')
            ORDER BY ep.side,ep.participant_id""",(event_id,)
    ).fetchall()
    out={}
    for side,pid,name in rows:
        out.setdefault(side,(pid,name))
    return out.get('A'),out.get('B')


def _prior_record(c,sport,participant_id,prediction_cutoff):
    """PIT-safe future-inference prior using publication time or proven retrieval time."""
    pit_clause = """(
        (
            ss.availability_status='EXACT'
            AND ss.source_available_at_utc IS NOT NULL
            AND datetime(ss.source_available_at_utc) <= datetime(?)
        )
        OR
        (
            ss.source_available_at_utc IS NULL
            AND ss.retrieved_at_utc IS NOT NULL
            AND datetime(ss.retrieved_at_utc) <= datetime(?)
        )
    )"""
    common = f"""
             FROM event e
             JOIN event_participant ep ON ep.event_id=e.event_id
             JOIN event_outcome o ON o.event_id=e.event_id
             JOIN source_snapshot ss
              ON ss.source_url=o.source_url
             AND ss.event_time_utc=e.event_time_utc
            WHERE e.sport=? AND ep.participant_id=?
              AND e.event_time_utc < ?
              AND e.status IN ('COMPLETED','FINISHED','POST','FINAL')
              AND o.outcome_status='VERIFIED'
              AND {pit_clause}
    """
    starts=c.execute(
        "SELECT COUNT(DISTINCT e.event_id) " + common,
        (sport,participant_id,prediction_cutoff,prediction_cutoff,prediction_cutoff),
    ).fetchone()[0]
    wins=c.execute(
        "SELECT COUNT(DISTINCT e.event_id) " + common + " AND o.outcome=ep.side",
        (sport,participant_id,prediction_cutoff,prediction_cutoff,prediction_cutoff),
    ).fetchone()[0]
    starts=int(starts or 0); wins=int(wins or 0)
    return starts,wins,(wins+1.0)/(starts+2.0)


def _safe_prior_binary(c,s,now):
    future=_future_events(c,s,now)
    outputs=[]
    for eid,meta in future.items():
        if meta['participant_count']!=2:
            continue
        a,b=_participant_sides(c,eid)
        if not a or not b:
            continue
        event_time=meta['event_time_utc']
        cutoff=(datetime.fromisoformat(str(event_time).replace('Z','+00:00'))-__import__('datetime').timedelta(minutes=PIT_LEAD_MINUTES)).isoformat()
        sa,wa,rate_a=_prior_record(c,s,a[0],cutoff)
        sb,wb,rate_b=_prior_record(c,s,b[0],cutoff)
        denom=max(rate_a+rate_b,1e-12)
        pb=float(np.clip(rate_b/denom,1e-6,1-1e-6))
        features={
            'prior_starts_a':sa,'prior_wins_a':wa,'prior_win_rate_a':rate_a,
            'prior_starts_b':sb,'prior_wins_b':wb,'prior_win_rate_b':rate_b,
            'fallback_policy':'pit_safe_historical_prior_v2_retrieval_pit',
        }
        pid=_persist_forward_prediction(
            c,eid,s,cutoff,now,1.0-pb,pb,'safe_prior','safe-prior-v1',
            'pit-safe-historical-win-rate-v1',features
        )
        outputs.append({
            'event_id':eid,'event_time_utc':event_time,'prediction_cutoff_at_utc':cutoff,
            'side_a':a[1],'side_b':b[1],
            'probability_side_b':pb,'probability_side_a':1.0-pb,
            'strategy':'safe_prior','router_status':'SAFE_PRIOR_FALLBACK',
            'prediction_id':pid,'models':['historical_prior'],'ensemble_weights':None,
            'model_version':'safe-prior-v1','feature_version':'pit-safe-historical-win-rate-v1',
            'confidence':'LOW','action_state':'PASS',
            'situation':{'status':'PIT_SAFE','quality':{'evidence_count':sa+sb,'conflict_rate':None,'freshness_score':None},'policy':'historical outcomes only; no current unavailable information inferred'},
            'generated_at_utc':now.isoformat(),
        })
    return {'sport':s,'status':'PREDICTED_SAFE_PRIOR' if outputs else 'NO_FUTURE_EVENTS','predictions':outputs,'count':len(outputs)}


def _safe_prior_f1(c,now):
    future=_future_events(c,'f1',now)
    outputs=[]
    for eid,meta in future.items():
        event_time=meta['event_time_utc']
        cutoff=(datetime.fromisoformat(str(event_time).replace('Z','+00:00'))-__import__('datetime').timedelta(minutes=PIT_LEAD_MINUTES)).isoformat()
        drivers=c.execute(
            """SELECT DISTINCT ep.participant_id,p.canonical_name
                 FROM event_participant ep
                 LEFT JOIN participant p ON p.participant_id=ep.participant_id
                WHERE ep.event_id=? AND lower(coalesce(ep.role,''))='driver'
                ORDER BY ep.participant_id""",(eid,)
        ).fetchall()
        field_source="EVENT_CONFIRMED_PARTICIPANTS"
        field_status="EVENT_PARTICIPANTS_CONFIRMED"
        roster_retrieved=None
        if len(drivers)<2:
            roster=_current_f1_roster(now)
            if not roster:
                continue
            roster_retrieved,roster_names=roster
            if roster_retrieved > datetime.fromisoformat(cutoff.replace("Z","+00:00")):
                continue
            drivers=[]
            for name in roster_names:
                pid=hashlib.sha256(f"f1|driver|{name}".encode()).hexdigest()[:32]
                drivers.append((pid,name))
            if len(drivers)<2:
                continue
            field_source="FORMULA1_OFFICIAL_CURRENT_DRIVER_ROSTER"
            field_status="CURRENT_ROSTER_NOT_EVENT_CONFIRMED"
        scored=[]
        for pid,name in drivers:
            starts=c.execute(
                """SELECT COUNT(DISTINCT ms.event_id)
                     FROM match_stats ms JOIN event e ON e.event_id=ms.event_id
                     JOIN source_snapshot ss
                       ON ss.source_url=ms.source_url
                      AND ss.event_time_utc=e.event_time_utc
                    WHERE ms.sport='f1' AND ms.participant_id=? AND ms.stat_name='results.position'
                      AND e.event_time_utc < ?
                      AND e.status IN ('COMPLETED','FINISHED','POST','FINAL')
                      AND ss.availability_status='EXACT'
                      AND ss.source_available_at_utc IS NOT NULL
                      AND datetime(ss.source_available_at_utc) <= datetime(?)""",
                (pid,cutoff,cutoff),
            ).fetchone()[0]
            wins=c.execute(
                """SELECT COUNT(*)
                     FROM match_stats ms JOIN event e ON e.event_id=ms.event_id
                     JOIN source_snapshot ss
                       ON ss.source_url=ms.source_url
                      AND ss.event_time_utc=e.event_time_utc
                    WHERE ms.sport='f1' AND ms.participant_id=? AND ms.stat_name='results.position'
                      AND ms.value_num=1 AND e.event_time_utc < ?
                      AND e.status IN ('COMPLETED','FINISHED','POST','FINAL')
                      AND ss.availability_status='EXACT'
                      AND ss.source_available_at_utc IS NOT NULL
                      AND datetime(ss.source_available_at_utc) <= datetime(?)""",
                (pid,cutoff,cutoff),
            ).fetchone()[0]
            scored.append((pid,name,int(starts or 0),int(wins or 0),(int(wins or 0)+1.0)/(int(starts or 0)+2.0)))
        total=sum(x[4] for x in scored)
        if total<=0:
            continue
        probs=[{'participant_id':pid,'name':name,'probability':float(score/total),'prior_starts':starts,'prior_wins':wins} for pid,name,starts,wins,score in scored]
        probs.sort(key=lambda x:(-x['probability'],x['participant_id']))
        outputs.append({
            'event_id':eid,'event_time_utc':event_time,'prediction_cutoff_at_utc':cutoff,
            'market':'winner_multiclass','strategy':'safe_prior_multiclass','model_version':'safe-prior-f1-v1',
            'feature_version':'pit-safe-f1-driver-win-prior-v1','drivers':probs,
            'field_source':field_source,'field_status':field_status,
            'field_roster_retrieved_at_utc':roster_retrieved.isoformat() if roster_retrieved else None,
            'confidence':'LOW','action_state':'PASS','generated_at_utc':now.isoformat(),
            'policy':'F1 multiclass safe prior; only pre-event completed driver results are used; current roster fallback is explicitly not event-confirmed',
        })
    return {'sport':'f1','status':'PREDICTED_SAFE_PRIOR_MULTICLASS' if outputs else 'NO_FUTURE_EVENTS','predictions':outputs,'count':len(outputs)}


def _prediction_confidence(probability, situation):
    """Conservative event-level confidence label; probabilities are unchanged."""
    max_p = max(float(probability), 1.0 - float(probability))
    quality = situation.get("quality") or {}
    conflict = quality.get("conflict_rate")
    freshness = quality.get("freshness_score")
    evidence = int(quality.get("evidence_count") or 0)
    if conflict is not None and float(conflict) > 0.50:
        return "LOW"
    if max_p >= 0.80 and (freshness is None or float(freshness) >= 0.50) and evidence >= 1:
        return "HIGH"
    if max_p >= 0.65:
        return "MEDIUM"
    return "LOW"


def _prediction_action(confidence, situation):
    """Keep prediction and decision separate; uncertain/conflicted events abstain."""
    quality = situation.get("quality") or {}
    conflict = quality.get("conflict_rate")
    if conflict is not None and float(conflict) > 0.50:
        return "PASS"
    if confidence == "HIGH":
        return "PRIMARY"
    if confidence == "MEDIUM":
        return "SECONDARY"
    return "PASS"


def _matchday_situation(event_id, event_time, cutoff):
    try:
        payload = matchday_intelligence.build_matchday_intelligence(event_id, cutoff, DB)
        f = payload.get("features") or {}
        vector = matchday_intelligence.router_context_vector(payload)
        q = {
            "source_diversity": f.get("matchday_source_diversity"),
            "conflict_rate": f.get("matchday_conflict_rate"),
            "confidence_mean": f.get("matchday_confidence_mean"),
            "freshness_score": f.get("matchday_freshness_score"),
            "evidence_count": sum(
                int(f.get(k) or 0)
                for k in ("weather_signal_count", "market_signal_count", "news_signal_count")
            ),
        }
        summary = {
            "availability_out_diff": (
                None if f.get("availability_out_side_a") is None or f.get("availability_out_side_b") is None
                else float(f.get("availability_out_side_a")) - float(f.get("availability_out_side_b"))
            ),
            "availability_uncertain_diff": (
                None if f.get("availability_uncertain_side_a") is None or f.get("availability_uncertain_side_b") is None
                else float(f.get("availability_uncertain_side_a")) - float(f.get("availability_uncertain_side_b"))
            ),
            "lineup_confirmed_diff": (
                None if f.get("lineup_confirmed_side_a") is None or f.get("lineup_confirmed_side_b") is None
                else float(f.get("lineup_confirmed_side_a")) - float(f.get("lineup_confirmed_side_b"))
            ),
            "rest_diff_days": None if not np.isfinite(vector[3]) else float(vector[3]),
            "weather_signal_count": f.get("weather_signal_count"),
            "market_signal_count": f.get("market_signal_count"),
            "news_signal_count": f.get("news_signal_count"),
            "lineup_known_a": f.get("lineup_known_side_a"),
            "lineup_known_b": f.get("lineup_known_side_b"),
        }
        return {
            "status": "PIT_SAFE",
            "cutoff_at_utc": cutoff,
            "quality": q,
            "summary": summary,
            "feature_snapshot_hash": payload.get("feature_snapshot_hash"),
            "policy": str(payload.get("policy") or "research_only;PIT"),
        }
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "cutoff_at_utc": cutoff,
            "quality": {
                "source_diversity": None,
                "conflict_rate": None,
                "confidence_mean": None,
                "freshness_score": None,
                "evidence_count": 0,
            },
            "summary": {},
            "feature_snapshot_hash": None,
            "policy": "research_only;PIT",
            "reason": type(exc).__name__,
        }


def _persist_forward_prediction(c, event_id, sport, cutoff, now, pa, pb, strategy, model_version, feature_version, features):
    payload={k:features.get(k) for k in sorted(features)}
    fh=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()
    pid=_prediction_id(event_id,model_version,cutoff)
    c.execute(
        """INSERT OR IGNORE INTO forward_prediction
        (prediction_id,event_id,sport,market,prediction_cutoff_at_utc,generated_at_utc,
         probability_side_a,probability_side_b,strategy,model_version,feature_version,
         features_json,feature_snapshot_hash,status,created_at_utc)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (pid,event_id,sport,'winner',cutoff,now.isoformat(),float(pa),float(pb),strategy,
         str(model_version or ''),str(feature_version or ''),json.dumps(payload,ensure_ascii=False,sort_keys=True,default=str),
         fh,'OPEN',now.isoformat())
    )
    return pid


def predict_sport(c,s,now):
    # Every sport is a mandatory prediction lane. F1 has distinct multiclass semantics;
    # sports without an accepted production artifact use an explicit PIT-safe historical-prior
    # prediction instead of silently disappearing from the output.
    if s=='f1':
        return _safe_prior_f1(c,now)
    artifact_path=MODELS/f'{s}_current.joblib'
    if not artifact_path.is_file() or artifact_path.stat().st_size<=0:
        return _safe_prior_binary(c,s,now)
    try:
        artifact=joblib.load(artifact_path)
    except Exception:
        # A corrupt/unreadable artifact must never make the mandatory prediction
        # lane disappear. Fall back to the explicit PIT-safe prior.
        return _safe_prior_binary(c,s,now)
    if artifact.get('quality_status') not in ('ACCEPTED_LOCKED_HOLDOUT','ACCEPTED_AFTER_LOCKED_HOLDOUT'):
        # Candidate/deferred artifacts are never used as production models, but
        # the event still receives the mandatory explicitly-labelled safe prior.
        return _safe_prior_binary(c,s,now)
    features=list(artifact.get('features') or [])
    models=list(artifact.get('models') or [])
    names=list(artifact.get('model_names') or [])
    weights=artifact.get('ensemble_weights') or {}
    if not features or not models or not names or len(models)!=len(names):
        return {'sport':s,'status':'BLOCKED_ARTIFACT_SCHEMA'}
    router_status=str(artifact.get('dynamic_router_status') or 'FALLBACK_FIXED_ENSEMBLE')
    router_obj=artifact.get('dynamic_router')
    if router_status=='PRODUCTION_ROUTABLE_AFTER_GATES' and router_obj is None:
        return _safe_prior_binary(c,s,now)
    rows,_=base.build(c,s,include_unlabeled=True)
    available_features=set()
    for _,_,_,row_features in rows:
        available_features.update(row_features.keys())
    missing_schema=sorted(set(features)-available_features)
    if missing_schema:
        # Never synthesize missing model features. Use the PIT-safe fallback
        # instead, which depends only on pre-event verified historical outcomes.
        return _safe_prior_binary(c,s,now)
    future=_future_events(c,s,now)
    outputs=[]
    router_status=str(artifact.get('dynamic_router_status') or 'FALLBACK_FIXED_ENSEMBLE')
    use_router=router_status=='PRODUCTION_ROUTABLE_AFTER_GATES' and artifact.get('dynamic_router') is not None
    rnames=list(artifact.get('dynamic_router_names') or [])
    rmodels=artifact.get('dynamic_router_models') or {}
    rref=artifact.get('dynamic_router_feature_reference') if artifact.get('dynamic_router_feature_reference') is not None else None
    cal=artifact.get('probability_calibrator')
    cal_method=str((artifact.get('probability_calibration') or {}).get('method') or 'none')
    for eid,t,label,row_features in rows:
        meta=future.get(eid)
        if meta is None:
            continue
        if s in HEAD_TO_HEAD_SPORTS and meta['participant_count']!=2:
            continue
        if s in MULTICLASS_SPORTS and meta['participant_count'] < 2:
            continue
        # F1 is a true multi-entrant market. Do not silently force a binary
        # A/B artifact into production. Until a gated multiclass artifact schema
        # exists, fail closed for F1 rather than emitting an invalid winner model.
        if s in MULTICLASS_SPORTS:
            return {
                'sport': s,
                'status': 'DEFERRED_MULTICLASS_ARTIFACT_SCHEMA',
                'reason': 'F1 requires a gated per-driver multiclass winner artifact; binary A/B artifacts are never accepted'
            }
        x=np.asarray([[row_features.get(f,np.nan) for f in features]],dtype=float)
        if use_router and rref is not None and rnames and all(n in rmodels for n in rnames):
            rbase=[rmodels[n] for n in rnames]
            raw,router_meta=router.predict_with_router(
                artifact['dynamic_router'],rbase,rnames,rref,x,baseline_weights=weights
            )
            strategy = (
                str(artifact.get('ensemble_strategy') or 'fixed_equal_weight')
                if router_meta.get('fallback')
                else 'contextual_router'
            )
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
        cutoff=(datetime.fromisoformat(str(t).replace('Z','+00:00'))-__import__('datetime').timedelta(minutes=PIT_LEAD_MINUTES)).isoformat()
        situation=_matchday_situation(eid,t,cutoff)
        confidence=_prediction_confidence(p,situation)
        action_state=_prediction_action(confidence,situation)
        a,b=c.execute(
            """SELECT GROUP_CONCAT(CASE WHEN side='A' THEN canonical_name END),
                      GROUP_CONCAT(CASE WHEN side='B' THEN canonical_name END)
                 FROM event_participant ep
                 LEFT JOIN participant p ON p.participant_id=ep.participant_id
                WHERE ep.event_id=?""",(eid,)).fetchone()
        prediction_id=_persist_forward_prediction(
            c,eid,s,cutoff,now,1.0-p,p,strategy,artifact.get('model_version'),
            artifact.get('feature_version') or 'unknown',
            {
                **{f:row_features.get(f) for f in features},
                "matchday_situation": situation,
            }
        )
        outputs.append({
            'event_id':eid,'event_time_utc':t,'prediction_cutoff_at_utc':cutoff,'side_a':a,'side_b':b,
            'probability_side_b':p,'probability_side_a':1.0-p,
            'strategy':strategy,'router_status':router_status,'prediction_id':prediction_id,
            'models':list(names) if strategy!='contextual_router' else list(rnames),
            'ensemble_weights':dict(weights) if strategy!='contextual_router' else None,
            'model_version':artifact.get('model_version'),
            'feature_version':artifact.get('feature_version') or 'unknown',
            'confidence':confidence,
            'action_state':action_state,
            'situation':situation,
            'generated_at_utc':now.isoformat(),
        })
    return {'sport':s,'status':'PREDICTED' if outputs else 'NO_FUTURE_EVENTS',
            'predictions':outputs,'count':len(outputs)}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--sport',choices=SPORTS);args=ap.parse_args()
    now=utc_now()
    sports=[args.sport] if args.sport else list(SPORTS)
    results=[]
    for s in sports:
        db_path=DEDICATED_DBS.get(s,DB)
        if not db_path.exists() or db_path.stat().st_size<=0:
            results.append({'sport':s,'status':'PREDICTION_UNAVAILABLE_NO_DATA'})
            continue
        con=sqlite3.connect(db_path)
        try:
            results.append(predict_sport(con,s,now))
            # Export both newly-created and previously persisted forward predictions.
            experience.archive_forward_prediction_db(con, s, now.isoformat())
            con.commit()
        except Exception as exc:
            results.append({'sport':s,'status':'PREDICTION_BLOCKED_RUNTIME','reason':type(exc).__name__})
        finally:
            con.close()
    report={'generated_at_utc':now.isoformat(),'policy':'nine-sport-mandatory; accepted-artifact-first; PIT-safe research features; explicit safe-prior fallback; F1 multiclass safe-prior lane; gated contextual routing; frozen-holdout-validated calibration; event-confidence-v1; matchday-situation-v1','sports':results}
    archive_status=experience.archive_predictions(results, now.isoformat())
    report['experience_archive']=archive_status
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    # Derive eligibility from this exact canonical inference pass so the
    # eligibility artifact cannot become stale relative to future_predictions.
    eligibility=[]
    for item in results:
        status=str(item.get('status') or '')
        predictions=item.get('predictions') or []
        reasons={}
        if predictions:
            reasons['ELIGIBLE']=len(predictions)
        elif status:
            reasons[status]=int(item.get('count') or 0)
        eligibility.append({
            'sport':item.get('sport'),
            'generated_at_utc':now.isoformat(),
            'eligible_future_events':len(predictions),
            'reasons':reasons,
            'status':status,
        })
    eligibility_report={
        'timestamp_utc':now.isoformat(),
        'policy':'prediction-eligibility-v3-derived-from-canonical-future-inference',
        'sports':eligibility,
    }
    ELIGIBILITY_OUT.write_text(
        json.dumps(eligibility_report,ensure_ascii=False,indent=2),
        encoding='utf-8'
    )
    print(json.dumps(report,ensure_ascii=False,indent=2))
    blocked=[r for r in results if str(r.get('status','')).startswith('BLOCKED_')]
    return 1 if blocked else 0


if __name__=='__main__':
    raise SystemExit(main())
