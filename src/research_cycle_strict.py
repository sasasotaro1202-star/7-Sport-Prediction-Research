from __future__ import annotations
import hashlib,json,sqlite3,subprocess
from pathlib import Path
from itertools import combinations
import joblib,numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression
from src import research_cycle_v4 as base
from src import dynamic_model_router as router
from src import uncertainty_dynamic_router_oos as uncertainty_router
from src import matchday_intelligence_oos as matchday_intelligence
from src import case_risk_oos as case_risk
ROOT=Path(__file__).resolve().parents[1];DB=ROOT/'data/db/sports_v45.sqlite';MODELS=ROOT/'models/research';RESULTS=ROOT/'results/research'
SPORTS=('valorant','basketball','volleyball','ufc','rizin')
DEFERRED_SPORTS=('tennis','f1','rugby','boxing')
ALL_SPORTS=SPORTS+DEFERRED_SPORTS
def utc():
 from datetime import datetime,timezone
 return datetime.now(timezone.utc).isoformat()
def h(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()[:16]

def _json_safe(x):
 if isinstance(x,(float,np.floating)):
  return float(x) if np.isfinite(x) else None
 if isinstance(x,dict):
  return {str(k):_json_safe(v) for k,v in x.items()}
 if isinstance(x,(list,tuple)):
  return [_json_safe(v) for v in x]
 return x

def _json_dump(x,**kwargs):
 return json.dumps(_json_safe(x),ensure_ascii=False,allow_nan=False,**kwargs)
def f1():
 c=sqlite3.connect(DB)
 try:n=c.execute("select count(*) from event where sport='f1'").fetchone()[0];e=c.execute("select count(*) from source_snapshot where source='OpenF1' and availability_status='EXACT'").fetchone()[0]
 finally:c.close()
 return {'sport':'f1','status':'DEFERRED_PIT','events':int(n),'exact_pit_source_snapshots':int(e),'reason':'OpenF1 historical availability is not proven before the 60-minute cutoff; no leakage-prone proxy is permitted'}
def boxing():
 return _write_result('boxing',{'sport':'boxing','status':'DEFERRED_PIT','reason':'No free historical boxing source currently proves source availability before the 60-minute prediction cutoff; public/current schedule data is not historical PIT evidence.','source_candidates':['Boxing Undefeated open-boxing-data','BoxingScene','BoxRec-compatible public tooling'],'feature_policy_candidates':['weight_class','fighter_age','height_reach','stance','recent_winrate','opponent_strength','inactivity_days','weight_class_elo','result_method_prior'],'promotion_policy':'chronological OOS + frozen holdout + calibration + release gate required'})

def _temporal_calibration_candidate(p, y):
    """Choose calibration using multiple chronological pre-holdout windows only."""
    p=np.clip(np.asarray(p,dtype=float),1e-6,1-1e-6)
    y=np.asarray(y,int)
    n=len(p)
    if n<180 or len(np.unique(y))<2:
        return {'accepted':False,'method':'none','reason':'insufficient_preholdout_oos_for_calibration'}
    # Rolling-origin calibration validation: every validation block is strictly
    # after its fitting block. The blocks are disjoint, so a single lucky window
    # cannot decide the calibrator.
    train_ends=[max(60,int(n*0.50)),max(90,int(n*0.67)),max(120,int(n*0.80))]
    train_ends=sorted(set(min(n-30,x) for x in train_ends if x<n-20))
    folds=[]
    prev=0
    for i,te_start in enumerate(train_ends):
        te_end=train_ends[i+1] if i+1<len(train_ends) else n
        if te_end-te_start<25:
            continue
        if len(np.unique(y[:te_start]))<2 or len(np.unique(y[te_start:te_end]))<2:
            continue
        folds.append((te_start,te_end))
    if len(folds)<2:
        return {'accepted':False,'method':'none','reason':'insufficient_temporal_calibration_folds'}
    def _fit_predict(method, train_p, train_y, test_p):
        if method=='none':
            return np.clip(test_p,1e-6,1-1e-6),None
        if method=='sigmoid':
            model=LogisticRegression(C=0.25,max_iter=2000,random_state=42)
            model.fit(np.log(train_p/(1.0-train_p)).reshape(-1,1),train_y)
            z=np.log(test_p/(1.0-test_p)).reshape(-1,1)
            return np.clip(model.predict_proba(z)[:,1],1e-6,1-1e-6),model
        if method=='beta':
            model=LogisticRegression(C=0.25,max_iter=2000,random_state=43)
            model.fit(np.column_stack([np.log(train_p),np.log(1.0-train_p)]),train_y)
            z=np.column_stack([np.log(test_p),np.log(1.0-test_p)])
            return np.clip(model.predict_proba(z)[:,1],1e-6,1-1e-6),model
        if method=='isotonic':
            if len(train_p)<120 or len(np.unique(train_p))<25:
                return None,None
            model=IsotonicRegression(y_min=1e-6,y_max=1-1e-6,out_of_bounds='clip')
            model.fit(train_p,train_y)
            return np.clip(model.predict(test_p),1e-6,1-1e-6),model
        raise ValueError(method)

    methods=['none','sigmoid','beta','isotonic']
    fold_results={m:[] for m in methods}
    for method in methods:
        for te_start,te_end in folds:
            pred,_=_fit_predict(method,p[:te_start],y[:te_start],p[te_start:te_end])
            if pred is None:
                continue
            fold_results[method].append(base.metric(y[te_start:te_end],pred))
    raw_folds=fold_results['none']
    if len(raw_folds)<2:
        return {'accepted':False,'method':'none','reason':'raw_calibration_validation_unavailable'}

    def _aggregate(ms):
        keys=('logloss','brier','ece','accuracy','n')
        out={}
        for k in keys:
            vals=[float(m[k]) for m in ms if k in m and np.isfinite(float(m[k]))]
            out[k]=float(np.mean(vals)) if vals else float('inf')
        out['folds']=int(len(ms))
        out['logloss_std']=float(np.std([float(m['logloss']) for m in ms],ddof=1)) if len(ms)>1 else 0.0
        out['brier_std']=float(np.std([float(m['brier']) for m in ms],ddof=1)) if len(ms)>1 else 0.0
        out['ece_std']=float(np.std([float(m['ece']) for m in ms],ddof=1)) if len(ms)>1 else 0.0
        out['objective']=float(out['logloss']+0.05*out['logloss_std'])
        return out

    aggregated={m:_aggregate(v) for m,v in fold_results.items() if v}
    raw=aggregated['none']
    valid={m:v for m,v in aggregated.items() if m=='none' or v['folds']>=2}
    method=min(valid,key=lambda m:(valid[m]['objective'],valid[m]['brier'],valid[m]['ece']))
    score=valid[method]
    required=max(0.001,0.003*raw['logloss'])
    accepted=(method!='none'
              and score['logloss']<=raw['logloss']-required
              and score['brier']<=raw['brier']+0.002
              and score['ece']<=raw['ece']+0.01)
    if not accepted:
        return {'accepted':False,'method':'none','reason':'temporal_preholdout_validation_did_not_pass',
                'raw_validation':raw,'candidate_methods':valid,
                'required_logloss_improvement':required,
                'validation_folds':[(int(a),int(b)) for a,b in folds]}
    if method=='sigmoid':
        final=LogisticRegression(C=0.25,max_iter=2000,random_state=42)
        final.fit(np.log(p/(1.0-p)).reshape(-1,1),y)
    elif method=='beta':
        final=LogisticRegression(C=0.25,max_iter=2000,random_state=43)
        final.fit(np.column_stack([np.log(p),np.log(1.0-p)]),y)
    else:
        final=IsotonicRegression(y_min=1e-6,y_max=1-1e-6,out_of_bounds='clip')
        final.fit(p,y)
    return {'accepted':True,'method':method,'model':final,'raw_validation':raw,
            'calibrated_validation':score,'candidate_methods':valid,
            'required_logloss_improvement':required,
            'validation_folds':[(int(a),int(b)) for a,b in folds]}

def _write_result(s, payload):
    """Persist every research outcome, including DEFERRED/REJECTED states."""
    RESULTS.mkdir(parents=True,exist_ok=True)
    (RESULTS/f'{s}.json').write_text(_json_dump(payload,indent=2),encoding='utf-8')
    return payload

def _carry_forward_previous(c, sport, previous, current_features):
    """Keep the last accepted production model during a transient PIT/data outage.
    This never creates a new model: it only re-registers an already accepted,
    holdout-frozen artifact when the current run cannot reproduce enough strict
    PIT rows. The feature schema must still match the current production schema.
    """
    if not isinstance(previous, dict) or previous.get("status") != "TRAINED":
        return None
    feature_version=str(previous.get("feature_version") or "")
    if not (feature_version.startswith("strict-pit-v13-") or feature_version.startswith("strict-pit-v14-") or feature_version.startswith("strict-pit-v15-") or feature_version.startswith("strict-pit-v16-") or feature_version.startswith("strict-pit-v17-") or feature_version.startswith("strict-pit-v18-") or feature_version.startswith("strict-pit-v19-")):
        return None
    artifact = _restore_historical_artifact(sport, previous)
    if artifact is None or not _artifact_features_compatible(artifact, current_features):
        return None
    required = ("model_version","feature_version","training_cutoff_utc",
                "git_commit_sha","artifact_path","holdout_metrics")
    if any(not previous.get(k) for k in required):
        return None
    hm = previous.get("holdout_metrics") or {}
    if any(k not in hm for k in ("logloss","brier","accuracy","ece","n")):
        return None
    meta = dict(previous)
    meta.update({
        "quality_status": "ACCEPTED_CARRY_FORWARD",
        "carry_forward": True,
        "carry_forward_reason": "current strict PIT rows temporarily insufficient; last accepted frozen-holdout artifact retained",
        "carry_forward_checked_at_utc": utc(),
        "carry_forward_artifact_bytes": artifact.stat().st_size,
    })
    sid = h({"sport":sport,"carry_forward":meta.get("model_version"),
             "artifact":str(artifact),"checked":meta["carry_forward_checked_at_utc"]})
    c.execute("INSERT OR REPLACE INTO model_state_snapshot(snapshot_id,sport,market,as_of_utc,model_version,feature_version,training_cutoff_utc,dataset_hash,git_commit_sha,artifact_path,quality_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
              (sid,sport,"winner",utc(),meta["model_version"],meta["feature_version"],
               meta["training_cutoff_utc"],h(meta),meta["git_commit_sha"],
               str(artifact.relative_to(ROOT)),"ACCEPTED_CARRY_FORWARD",
               _json_dump(meta)))
    c.commit()
    return meta

def _artifact_features_compatible(path, current_features):
    try:
        obj=joblib.load(path)
        old_features=set(obj.get("features") or [])
        return bool(old_features) and old_features.issubset(set(current_features))
    except Exception:
        return False

def _previous_result(sport):
    # Current result files are intentionally overwritten each run. Recover the
    # last historically TRAINED result from git when the current run is deferred.
    p=RESULTS/f'{sport}.json'
    if p.exists():
        try:
            current=json.loads(p.read_text(encoding="utf-8"))
            if current.get("status") == "TRAINED":
                return current
        except Exception:
            pass
    path=f"results/research/{sport}.json"
    try:
        # Inspect recent history directly instead of relying on git -S quoting.
        # Result JSON is a generated artifact, so exact textual pickaxe matching is
        # brittle across indentation/serialization changes.
        commits=subprocess.run(
            ["git","log","--format=%H","-n","300","--",path],
            cwd=ROOT,text=True,capture_output=True,check=False,timeout=30
        ).stdout.splitlines()
        for sha in commits:
            raw=subprocess.run(["git","show",f"{sha}:{path}"],cwd=ROOT,text=True,
                               capture_output=True,check=False,timeout=20)
            if raw.returncode != 0:
                continue
            try:
                obj=json.loads(raw.stdout)
            except Exception:
                continue
            if obj.get("status") == "TRAINED":
                obj["_historical_commit"] = sha
                return obj
    except Exception:
        pass
    return None

def _restore_historical_artifact(sport, previous):
    artifact_rel=str(previous.get("artifact_path") or f"models/research/{sport}_current.joblib")
    target=ROOT/artifact_rel
    if target.is_file() and target.stat().st_size>0 and _artifact_loadable(target):
        return target
    shas=[]
    for sha in (previous.get("_historical_commit"), previous.get("git_commit_sha")):
        if sha and sha not in shas: shas.append(sha)
    for sha in shas:
        try:
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open("wb") as out:
                p=subprocess.run(["git","show",f"{sha}:{artifact_rel}"],cwd=ROOT,
                                 stdout=out,stderr=subprocess.PIPE,check=False,timeout=60)
            if p.returncode==0 and target.is_file() and target.stat().st_size>0 and _artifact_loadable(target):
                return target
        except Exception:
            continue
    return None

def _artifact_loadable(path):
    try:
        obj=joblib.load(path)
        if not isinstance(obj, dict): return False
        if 'features' not in obj or not obj.get('features'): return False
        return True
    except Exception:
        return False

def _previous_model_from_db(c, sport):
    """Recover the last accepted model from the persistent partition DB.
    This is the primary continuity source; result JSON files are disposable outputs.
    """
    try:
        row=c.execute("SELECT metadata_json,model_version,feature_version,training_cutoff_utc,git_commit_sha,artifact_path,quality_status FROM model_state_snapshot WHERE sport=? AND market='winner' AND quality_status LIKE 'ACCEPTED%' ORDER BY as_of_utc DESC LIMIT 1",(sport,)).fetchone()
        if not row:
            return None
        payload=json.loads(row[0] or '{}')
        payload.setdefault('model_version',row[1]); payload.setdefault('feature_version',row[2])
        payload.setdefault('training_cutoff_utc',row[3]); payload.setdefault('git_commit_sha',row[4])
        payload.setdefault('artifact_path',row[5]); payload.setdefault('quality_status',row[6])
        payload['status']='TRAINED'
        payload['_db_recovered']=True
        return payload
    except Exception:
        return None


HOLDOUT_REGISTRY_VERSION='immutable-frozen-holdout-v1'

def _holdout_registry_path(sport):
 return RESULTS/f'{sport}_frozen_holdout.json'

def _load_or_create_frozen_holdout(sport, rows):
 """Freeze an exact event-id holdout once and reuse it for audit scoring."""
 path=_holdout_registry_path(sport)
 current={str(r[0]):r for r in rows}
 if path.exists():
  try:
   reg=json.loads(path.read_text(encoding='utf-8'))
  except Exception as exc:
   return {'status':'INVALID','reason':f'holdout_registry_unreadable:{exc!r}'}
  if reg.get('version')!=HOLDOUT_REGISTRY_VERSION or reg.get('sport')!=sport:
   return {'status':'INVALID','reason':'holdout_registry_version_or_sport_mismatch'}
  ids=[str(x) for x in (reg.get('event_ids') or [])]
  if not ids:
   return {'status':'INVALID','reason':'holdout_registry_empty'}
  missing=[eid for eid in ids if eid not in current]
  if missing:
   return {'status':'INVALID','reason':'frozen_holdout_event_missing','missing_event_count':len(missing)}
  return {'status':'OK','source':'persisted','event_ids':ids,
          'registry_hash':str(reg.get('registry_hash') or h(ids)),
          'freeze_cutoff_utc':reg.get('freeze_cutoff_utc'),
          'row_count_at_freeze':reg.get('row_count_at_freeze')}
 if len(rows)<120:
  return {'status':'DEFERRED','reason':'insufficient_rows_to_establish_frozen_holdout','rows':len(rows)}
 sel=int(len(rows)*.78); hn=len(rows)-sel
 if hn<30:
  return {'status':'DEFERRED','reason':'insufficient_rows_for_frozen_holdout','rows':len(rows),'holdout_rows':hn}
 ids=[str(r[0]) for r in rows[sel:]]
 payload={'version':HOLDOUT_REGISTRY_VERSION,'sport':sport,'event_ids':ids,
          'freeze_cutoff_utc':rows[sel][1],'holdout_last_event_time_utc':rows[-1][1],
          'row_count_at_freeze':len(rows),'holdout_rows_at_freeze':len(ids),'created_at_utc':utc()}
 payload['registry_hash']=h(payload)
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
 return {'status':'OK','source':'created','event_ids':ids,'registry_hash':payload['registry_hash'],
         'freeze_cutoff_utc':payload['freeze_cutoff_utc'],'row_count_at_freeze':len(rows)}


def _recent_weighted_route(bp, history_loss, baseline_weights=None,
                           temperature=0.12, max_strength=0.65, spread_scale=0.03):
    """Conservative recent-performance weighting using only pre-row OOF loss history."""
    bp=np.asarray(bp,dtype=float)
    if bp.ndim!=2 or bp.shape[1]<2:
        return None
    hl=np.asarray(history_loss,dtype=float)
    if hl.ndim!=1 or len(hl)!=bp.shape[1]:
        hl=np.full(bp.shape[1],np.log(2.0),dtype=float)
    hl=np.where(np.isfinite(hl),hl,np.log(2.0))
    if baseline_weights:
        base=np.asarray([float(baseline_weights.get(n,0.0)) for n in
                         getattr(_recent_weighted_route,"_names",[])],dtype=float)
    else:
        base=np.full(bp.shape[1],1.0/bp.shape[1],dtype=float)
    if len(base)!=bp.shape[1] or not np.isfinite(base).all() or base.sum()<=0:
        base=np.full(bp.shape[1],1.0/bp.shape[1],dtype=float)
    base=base/base.sum()
    # Lower recent loss gets more weight; multiplying by incumbent prior prevents
    # the adaptive layer from discarding a well-established production expert.
    centered=hl-np.min(hl)
    raw=base*np.exp(-centered/max(float(temperature),1e-3))
    if not np.isfinite(raw).all() or raw.sum()<=0:
        raw=base.copy()
    raw=raw/raw.sum()
    adaptive=0.75*raw+0.25*base
    spread=float(np.max(hl)-np.min(hl))
    strength=max_strength*float(np.clip(spread/max(spread+spread_scale,1e-9),0.0,1.0))
    weights=base+strength*(adaptive-base)
    weights=np.clip(weights,1e-6,None)
    weights/=weights.sum()
    return np.clip(np.sum(bp*weights[None,:],axis=1),1e-6,1-1e-6)

def evaluate_recent_weighted_router_from_folds(
    X, y, names, folds, baseline_weights=None,
):
    """Research-only OOS test of recent-loss weighted ensemble; fold t sees only losses from folds < t."""
    X=np.asarray(X,dtype=float); y=np.asarray(y)
    if len(names)<2 or len(folds)<3:
        return {"status":"INSUFFICIENT_OOS","reason":"too_few_chronological_folds"}
    meta_losses=[]; preds=[]; targets=[]; deltas=[]; used=0
    prev_names=getattr(_recent_weighted_route,"_names",None)
    _recent_weighted_route._names=list(names)
    try:
        for fold in folds:
            end=int(fold["end"]); te=int(fold["te"])
            bp=np.column_stack([np.asarray(fold["preds"][n],dtype=float) for n in names])
            hl=router._recent_model_loss(meta_losses,len(names))
            static=np.sum(
                bp*np.asarray([baseline_weights.get(n,0.0) for n in names])[None,:],
                axis=1
            ) if baseline_weights and sum(float(baseline_weights.get(n,0.0)) for n in names)>0 else np.mean(bp,axis=1)
            routed=_recent_weighted_route(bp,hl,baseline_weights)
            if routed is None: routed=static.copy()
            ym=y[end:te]
            sm=base.metric(ym,static); rm=base.metric(ym,routed)
            deltas.append(float(rm["logloss"]-sm["logloss"]))
            preds.extend(routed.tolist()); targets.extend(ym.tolist()); used+=1
            yt=ym.astype(float)
            fold_losses=-(yt[:,None]*np.log(bp)+(1.0-yt[:,None])*np.log(1.0-bp))
            meta_losses.extend(fold_losses.tolist())
    finally:
        _recent_weighted_route._names=prev_names
    if len(targets)<120 or len(meta_losses)<120:
        return {"status":"INSUFFICIENT_OOS","reason":"insufficient_router_training_oof","oos_rows":len(meta_losses)}
    static_pred=[]; static_y=[]
    for fold in folds:
        end=int(fold["end"]); te=int(fold["te"])
        bp=np.column_stack([np.asarray(fold["preds"][n],dtype=float) for n in names])
        if baseline_weights and sum(float(baseline_weights.get(n,0.0)) for n in names)>0:
            w=np.asarray([float(baseline_weights.get(n,0.0)) for n in names],dtype=float); w/=w.sum()
            p=np.sum(bp*w[None,:],axis=1)
        else: p=np.mean(bp,axis=1)
        static_pred.extend(p.tolist()); static_y.extend(y[end:te].tolist())
    sm=base.metric(np.asarray(static_y),np.asarray(static_pred))
    rm=base.metric(np.asarray(targets),np.asarray(preds))
    d=np.asarray(deltas,dtype=float)
    blocks=[]
    if len(d)>=3:
        for ids in np.array_split(np.arange(len(d)),3):
            if len(ids): blocks.append(float(np.mean(d[ids])))
    boot_p05=float("-inf"); boot_prob=0.0
    if len(d)>=6 and np.isfinite(d).all():
        rng=np.random.default_rng(20260925)
        idx=rng.integers(0,len(d),size=(1000,len(d)))
        imp=-d[idx].mean(axis=1)
        boot_p05=float(np.quantile(imp,0.05)); boot_prob=float(np.mean(imp>0.0))
    return {
        "status":"EVALUATED","folds":used,"oos_rows":len(meta_losses),
        "fixed_ensemble":sm,"recent_weighted_router":rm,
        "logloss_improvement":sm["logloss"]-rm["logloss"],
        "brier_improvement":sm["brier"]-rm["brier"],
        "ece_change":rm["ece"]-sm["ece"],
        "fold_logloss_deltas":d.tolist(),
        "nonoverlap_block_deltas":blocks,
        "bootstrap_p05_improvement":boot_p05,
        "bootstrap_prob_improvement":boot_prob,
        "policy":"research_only; chronological OOF; recent expert loss prior; no holdout fitting",
    }

def evaluate_recent_weighted_router_holdout_from_folds(
    X, y, names, folds, holdout_pred, holdout_X, holdout_y, baseline_weights=None,
):
    """Score recent-loss weighting on frozen holdout; all weights come from pre-holdout OOF."""
    X=np.asarray(X,dtype=float); y=np.asarray(y)
    hX=np.asarray(holdout_X,dtype=float); hy=np.asarray(holdout_y)
    if len(names)<2 or hX.ndim!=2 or len(hy)!=len(hX):
        return {"status":"INSUFFICIENT_HOLDOUT","reason":"invalid_holdout_shapes"}
    meta_losses=[]
    for fold in folds:
        end=int(fold["end"]); te=int(fold["te"])
        bp=np.column_stack([np.asarray(fold["preds"][n],dtype=float) for n in names])
        ym=y[end:te].astype(float)
        fold_losses=-(ym[:,None]*np.log(bp)+(1.0-ym[:,None])*np.log(1.0-bp))
        meta_losses.extend(fold_losses.tolist())
    if len(meta_losses)<120:
        return {"status":"INSUFFICIENT_OOS","reason":"insufficient_router_training_oof","oos_rows":len(meta_losses)}
    prev_names=getattr(_recent_weighted_route,"_names",None); _recent_weighted_route._names=list(names)
    try:
        bp=np.column_stack([np.asarray(holdout_pred[n],dtype=float) for n in names])
        hl=router._recent_model_loss(meta_losses,len(names))
        if baseline_weights and sum(float(baseline_weights.get(n,0.0)) for n in names)>0:
            w=np.asarray([float(baseline_weights.get(n,0.0)) for n in names],dtype=float); w/=w.sum()
            static=np.sum(bp*w[None,:],axis=1)
        else:
            static=np.mean(bp,axis=1)
        routed=_recent_weighted_route(bp,hl,baseline_weights)
    finally:
        _recent_weighted_route._names=prev_names
    if routed is None:
        return {"status":"INSUFFICIENT_OOS","reason":"recent_weighted_router_fit_failed","oos_rows":len(meta_losses)}
    sm=base.metric(hy.astype(int),static); rm=base.metric(hy.astype(int),routed)
    return {
        "status":"EVALUATED","oos_training_rows":len(meta_losses),"holdout_rows":len(hy),
        "fixed_ensemble":sm,"recent_weighted_router":rm,
        "logloss_improvement":sm["logloss"]-rm["logloss"],
        "brier_improvement":sm["brier"]-rm["brier"],
        "ece_change":rm["ece"]-sm["ece"],
        "policy":"research_only; weights fitted from pre-holdout OOF loss history; frozen holdout labels score-only",
    }

def train(s):
 if s=='f1':
  return _write_result(s,f1())
 c=sqlite3.connect(DB)
 try:
  previous=_previous_result(s) or _previous_model_from_db(c,s)
  rows,fs=base.build(c,s)
  if len(rows)<120:
   carried=_carry_forward_previous(c,s,previous,fs)
   payload={'sport':s,'status':'DEFERRED_RETRAIN_CARRY_FORWARD' if carried else 'DEFERRED','reason':'insufficient_strict_PIT_rows','rows':len(rows),'features':len(fs),'provenance_rule':'pre-cutoff observed feature or provenance-verified historical outcome required'}
   if carried:
    payload['carried_forward_model_version']=carried['model_version']
    payload['carried_forward_training_cutoff_utc']=carried['training_cutoff_utc']
    payload['carry_forward_artifact_path']=carried['artifact_path']
    payload['carry_forward_holdout_metrics']=carried.get('holdout_metrics')
   return _write_result(s,payload)
  registry=_load_or_create_frozen_holdout(s,rows)
  if registry.get('status')!='OK':
   return _write_result(s,{'sport':s,'status':'DEFERRED_FROZEN_HOLDOUT' if registry.get('status')=='DEFERRED' else 'REJECTED_FROZEN_HOLDOUT',**registry})
  holdout_event_ids=list(registry['event_ids']); holdout_set=set(holdout_event_ids)
  train_rows=[r for r in rows if str(r[0]) not in holdout_set]
  holdout_rows=[r for r in rows if str(r[0]) in holdout_set]
  if len(train_rows)<100 or len(holdout_rows)<30:
   return _write_result(s,{'sport':s,'status':'DEFERRED_FROZEN_HOLDOUT','reason':'frozen_holdout_partition_too_small','training_rows':len(train_rows),'holdout_rows':len(holdout_rows)})
  # Build the feature schema from training-only rows; the immutable holdout must not
  # determine feature existence or all-missing-column removal.
  fs=sorted({k for _,_,_,f in train_rows for k in f})
  X=np.array([[r[3].get(f,np.nan) for f in fs] for r in train_rows]);y=np.array([r[2] for r in train_rows])
  X_holdout=np.array([[r[3].get(f,np.nan) for f in fs] for r in holdout_rows]);y_holdout=np.array([r[2] for r in holdout_rows])
  # Never send all-missing columns into sklearn imputers. They carry no signal,
  # make feature schemas unstable across folds, and can trigger silent column drops.
  keep=np.isfinite(X).any(axis=0)
  if not keep.any():
   return _write_result(s,{'sport':s,'status':'DEFERRED','reason':'no_observed_feature_values','rows':len(train_rows),'features':0})
  fs=[f for f,k in zip(fs,keep) if k];X=X[:,keep];X_holdout=X_holdout[:,keep]
  sel=len(train_rows);hn=len(holdout_rows)
  # Matchday context is built only where the router can consume it: chronological
  # OOS test rows. The frozen holdout remains separate and immutable.
  matchday_holdout_ctx=np.asarray(
   matchday_intelligence.build_matchday_change_context_rows(holdout_rows),dtype=float
  )
  if matchday_holdout_ctx.shape!=(hn,20):
   return _write_result(s,{'sport':s,'status':'DEFERRED_MATCHDAY_CONTEXT','reason':'matchday_context_shape_mismatch',
                           'holdout_shape':list(matchday_holdout_ctx.shape)})
  # Construct the pool once per sport. Recreating every estimator wrapper for
  # every fold adds avoidable overhead without changing the fitted models.
  symmetric_mode=s in ('ufc','rizin')
  fold_pool=base.pool(fs, symmetric=symmetric_mode)
  names=list(fold_pool)
  # Multi-window walk-forward OOS: reuse one common fold set to evaluate
  # several historical windows, reducing sensitivity to one arbitrary start.
  # Bound fold density for large datasets: the promotion gates still require
  # at least six chronological folds, while excessive fold counts multiply
  # expensive tree/LightGBM fits with little additional temporal coverage.
  window_fracs=(0.55,0.60,0.65)
  window_starts=[max(60,int(sel*f)) for f in window_fracs]
  start=min(window_starts)
  target_oos_folds=min(12,max(6,sel//500))
  step=max(10,int(np.ceil(max(1,sel-start)/target_oos_folds)))
  oof_probs={name:[] for name in names}
  oof_y=[]
  oof_event_ids=[]
  oof_folds=[]
  oof_rows=[]
  for end in range(start,sel,step):
   te=min(end+step,sel)
   if len(np.unique(y[:end]))<2:continue
   fold_pred={}
   for name in names:
    m=fold_pool[name]
    m.fit(X[:end],y[:end])
    fold_pred[name]=np.clip(m.predict_proba(X[end:te])[:,1],1e-6,1-1e-6)
    oof_probs[name].extend(fold_pred[name].tolist())
   oof_y.extend(y[end:te].tolist())
   oof_event_ids.extend([str(r[0]) for r in train_rows[end:te]])
   base_router_ctx=router._context(X[:end],X[end:te])
   population_drift=uncertainty_router.population_drift_features(X[:end],X[end:te])
   population_ctx=np.repeat(population_drift[None,:],te-end,axis=0)
   oof_rows.extend(train_rows[end:te])
   oof_folds.append({'end':end,'te':te,'preds':fold_pred,'base_router_ctx':base_router_ctx,
                     'population_ctx':population_ctx,
                     'event_ids':[str(r[0]) for r in train_rows[end:te]],
                     'population_drift':population_drift.tolist()})
  matchday_oof_ctx=np.asarray(
   matchday_intelligence.build_matchday_change_context_rows(oof_rows),dtype=float
  )
  if matchday_oof_ctx.shape!=(len(oof_rows),20):
   return _write_result(s,{'sport':s,'status':'DEFERRED_MATCHDAY_CONTEXT','reason':'matchday_context_shape_mismatch',
                           'oos_shape':list(matchday_oof_ctx.shape),'expected_rows':len(oof_rows)})
  ctx_offset=0
  for fold in oof_folds:
   n_fold=fold['te']-fold['end']
   base_router_ctx=fold.pop('base_router_ctx')
   population_ctx=fold.pop('population_ctx')
   fold['context']=np.column_stack([base_router_ctx,matchday_oof_ctx[ctx_offset:ctx_offset+n_fold],population_ctx])
   ctx_offset+=n_fold
  oof_y=np.asarray(oof_y,int)
  if len(oof_y)<30 or len(np.unique(oof_y))<2:
   return _write_result(s,{'sport':s,'status':'DEFERRED','reason':'no_valid_walk_forward_folds','rows':len(rows)})
  def _window_metric_for_preds(pred_by_fold):
   """Evaluate three non-overlapping chronological OOS blocks."""
   out=[]
   if len(oof_folds)<3:
    return out
   for fold_ids in np.array_split(np.arange(len(oof_folds)),3):
    yy=[];pp=[]
    for fi in fold_ids.tolist():
     fold=oof_folds[int(fi)]
     yy.extend(y[int(fold['end']):int(fold['te'])].tolist())
     pp.extend(pred_by_fold[int(fold['end'])])
    if len(yy)>=20 and len(np.unique(yy))>1:
     out.append(base.metric(np.asarray(yy),np.asarray(pp)))
   return out
  def _regime_robust_objective(spec, weights=None):
   """Score pre-holdout OOF performance across a few fixed, PIT-safe regimes."""
   regime_scores=[]
   overall_pred=[]
   overall_y=[]
   for fold in oof_folds:
    end=int(fold['end']);te=int(fold['te'])
    fp=np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in spec])
    p=np.mean(fp,axis=1) if weights is None else np.sum(fp*np.array([weights[n] for n in spec])[None,:],axis=1)
    yy=y[end:te]
    overall_pred.extend(p.tolist());overall_y.extend(yy.tolist())
   overall=np.asarray(overall_pred,float)
   target=np.asarray(overall_y,int)
   base_ll=base.metric(target,overall)['logloss'] if len(target) else float('inf')
   regime_names=[
    'competition_is_asian_games','competition_is_bleague',
    'D__short_rest_flag','D__games_last_7d','D__games_last_30d',
    'D__recent_form_delta','D__elo_momentum'
   ]
   fs_index={name:i for i,name in enumerate(fs)}
   for rn in regime_names:
    idx=fs_index.get(rn)
    if idx is None:continue
    vals=[];labels=[]
    for fold in oof_folds:
     end=int(fold['end']);te=int(fold['te'])
     fp=np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in spec])
     p=np.mean(fp,axis=1) if weights is None else np.sum(fp*np.array([weights[n] for n in spec])[None,:],axis=1)
     yy=y[end:te]
     z=X[end:te,idx]
     finite=np.isfinite(z)
     if not np.any(finite):continue
     if rn in ('competition_is_asian_games','competition_is_bleague','D__short_rest_flag'):
      group=(z>=0.5)
      for g in (False,True):
       m=finite & (group==g)
       if m.sum()>=20 and len(np.unique(yy[m]))>1:
        regime_scores.append((rn,str(g),base.metric(yy[m],p[m])['logloss'],int(m.sum())))
     else:
      zv=z[finite]
      if zv.size<40:continue
      med=float(np.nanmedian(zv))
      for label,g in (('low',finite&(z<=med)),('high',finite&(z>med))):
       if g.sum()>=20 and len(np.unique(yy[g]))>1:
        regime_scores.append((rn,label,base.metric(yy[g],p[g])['logloss'],int(g.sum())))
   if not regime_scores:
    return base_ll,0.0,[]
   worst=max(z[2] for z in regime_scores)
   excess=max(0.0,worst-base_ll)
   return base_ll,excess,regime_scores

  oos={}
  for name in names:
   p=np.asarray(oof_probs[name],float)
   score=base.metric(oof_y,p)
   fold_ll=[];fold_brier=[]
   for fold in oof_folds:
    yy=y[int(fold['end']):int(fold['te'])]
    pred=np.asarray(fold['preds'][name],dtype=float)
    fold_ll.append(base.metric(yy,pred)['logloss'])
    fold_brier.append(base.metric(yy,pred)['brier'])
   win_scores=_window_metric_for_preds({int(f['end']):f['preds'][name] for f in oof_folds})
   win_ll=np.asarray([z['logloss'] for z in win_scores],dtype=float)
   win_brier=np.asarray([z['brier'] for z in win_scores],dtype=float)
   score['fold_logloss_std']=float(np.std(fold_ll)) if fold_ll else float('inf')
   score['fold_brier_std']=float(np.std(fold_brier)) if fold_brier else float('inf')
   score['window_logloss_mean']=float(np.mean(win_ll)) if len(win_ll) else float('inf')
   score['window_logloss_std']=float(np.std(win_ll)) if len(win_ll) else float('inf')
   score['window_brier_mean']=float(np.mean(win_brier)) if len(win_brier) else float('inf')
   score['window_count']=int(len(win_scores))
   # Recent windows receive more weight, while dispersion penalizes brittle edges.
   if len(win_scores)==3:
    recent_weights=np.array([0.20,0.30,0.50])
    score['robust_window_objective']=float(np.average(win_ll,weights=recent_weights)+0.10*np.std(win_ll))
   else:
    score['robust_window_objective']=float(score['logloss']+0.10*score['fold_logloss_std'])
   base_ll,regime_excess,regime_scores=_regime_robust_objective((name,),None)
   score['regime_worst_excess']=float(regime_excess)
   score['regime_groups']=len(regime_scores)
   score['robust_objective']=score['robust_window_objective']+0.05*score['fold_logloss_std']+0.15*regime_excess
   oos[name]=score
  if not oos:return _write_result(s,{'sport':s,'status':'DEFERRED','reason':'no_valid_walk_forward_folds','rows':len(rows)})
  rank=sorted(oos,key=lambda k:(oos[k]['robust_objective'],oos[k]['brier'],oos[k]['ece']))
  top_rank=rank[:4]
  cands=[(n,) for n in top_rank]+list(combinations(top_rank,2))+list(combinations(top_rank,3))
  scores={}
  for spec in cands:
   key='+'.join(spec)
   if len(spec)==1:
    p=np.asarray(oof_probs[spec[0]],float)
   else:
    p=np.mean(np.column_stack([oof_probs[n] for n in spec]),axis=1)
   score=base.metric(oof_y,p)
   fold_ll=[];fold_brier=[]
   window_scores=_window_metric_for_preds({
    int(fold['end']): np.mean(
      np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in spec]),
      axis=1
    ).tolist()
    for fold in oof_folds
   })
   for fold in oof_folds:
    fp=np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in spec])
    pred=np.mean(fp,axis=1)
    yy=y[int(fold['end']):int(fold['te'])]
    fold_ll.append(base.metric(yy,pred)['logloss'])
    fold_brier.append(base.metric(yy,pred)['brier'])
   wll=np.asarray([z['logloss'] for z in window_scores],dtype=float)
   wb=np.asarray([z['brier'] for z in window_scores],dtype=float)
   score['fold_logloss_std']=float(np.std(fold_ll)) if fold_ll else float('inf')
   score['fold_brier_std']=float(np.std(fold_brier)) if fold_brier else float('inf')
   score['window_logloss_mean']=float(np.mean(wll)) if len(wll) else float('inf')
   score['window_logloss_std']=float(np.std(wll)) if len(wll) else float('inf')
   score['window_brier_mean']=float(np.mean(wb)) if len(wb) else float('inf')
   score['window_count']=len(window_scores)
   if len(window_scores)==3:
    score['robust_window_objective']=float(np.average(wll,weights=np.array([0.20,0.30,0.50]))+0.10*np.std(wll))
   else:
    score['robust_window_objective']=float(score['logloss']+0.10*score['fold_logloss_std'])
   _,regime_excess,regime_scores=_regime_robust_objective(spec,None)
   score['regime_worst_excess']=float(regime_excess)
   score['regime_groups']=len(regime_scores)
   score['robust_objective']=score['robust_window_objective']+0.05*score['fold_logloss_std']+0.15*regime_excess
   score['folds']=len(fold_ll)
   scores[key]=score
  if not scores:return _write_result(s,{'sport':s,'status':'DEFERRED','reason':'no_valid_ensemble_selection_folds','rows':len(rows)})
  # Candidate selection is strictly pre-holdout. Equal-weight and bounded weighted
  # ensembles are compared on chronological OOS robustness only.
  best_fixed_key=min(scores,key=lambda k:(scores[k]['robust_objective'],scores[k]['brier'],scores[k]['ece']))
  fixed_models=tuple(best_fixed_key.split('+'))
  fixed_oos_metric=scores[best_fixed_key]
  best=fixed_models
  candidate_label='fixed_equal_weight'
  candidate_weights={name:1.0/len(best) for name in best}
  wa_a=wa_b=None;wa_weight=0.5;wa_metric=None
  wa_win_rate=0.0;wa_mean_delta=0.0;wa_fold_std=float('inf');wa_robust_gain=0.0


  def _weighted_candidate_score(spec, weights):
   p_all=np.sum(np.column_stack([weights.get(n,0.0)*np.asarray(oof_probs[n],float) for n in spec]),axis=1)
   overall=base.metric(oof_y,p_all)
   fold_losses=[]
   window_scores=_window_metric_for_preds({
    int(fold['end']): np.sum(
      np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in spec])*
                       np.array([weights[n] for n in spec])[None,:],
      axis=1
    ).tolist()
    for fold in oof_folds
   })
   for fold in oof_folds:
    yy=y[int(fold['end']):int(fold['te'])]
    fp=np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in spec])
    pp=np.sum(fp*np.array([weights[n] for n in spec])[None,:],axis=1)
    if len(yy)>=20 and len(np.unique(yy))>1:
     fold_losses.append(base.metric(yy,pp)['logloss'])
   wl=np.asarray([m['logloss'] for m in window_scores],dtype=float)
   robust=float(np.average(wl,weights=np.array([0.20,0.30,0.50]))+0.10*np.std(wl)+0.05*np.std(fold_losses)) if len(window_scores)==3 else float(overall['logloss']+0.15*np.std(fold_losses))
   return overall,robust,fold_losses,window_scores

  def _nonoverlap_block_deltas(spec, weights, fixed_spec):
   """Return candidate-minus-fixed LogLoss deltas for 3 disjoint OOS blocks."""
   deltas=[]
   if len(oof_folds)<3:
    return deltas
   for fold_ids in np.array_split(np.arange(len(oof_folds)),3):
    cy=[];cp=[];fp=[]
    for fi in fold_ids.tolist():
     fold=oof_folds[int(fi)]
     yy=y[int(fold['end']):int(fold['te'])]
     cpred=np.sum(
       np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in spec])*
                        np.array([weights[n] for n in spec])[None,:],
       axis=1
     )
     fpred=np.mean(
       np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in fixed_spec]),
       axis=1
     )
     cy.extend(yy.tolist());cp.extend(cpred.tolist());fp.extend(fpred.tolist())
    if len(cy)>=20 and len(np.unique(cy))>1:
     deltas.append(float(base.metric(np.asarray(cy),np.asarray(cp))['logloss']
                       -base.metric(np.asarray(cy),np.asarray(fp))['logloss']))
   return deltas

  def _paired_fold_delta_stats(spec, weights, fixed_spec):
   """Estimate paired fold uncertainty using only pre-holdout OOS folds."""
   cand=[];fixed=[]
   for fold in oof_folds:
    yy=y[int(fold['end']):int(fold['te'])]
    if len(yy)<20 or len(np.unique(yy))<2: continue
    cp=np.sum(np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in spec])*
                              np.array([weights[n] for n in spec])[None,:],axis=1)
    fp=np.mean(np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in fixed_spec]),axis=1)
    cand.append(base.metric(yy,cp)['logloss'])
    fixed.append(base.metric(yy,fp)['logloss'])
   if len(cand)<3:
    return {'mean_delta':0.0,'std_delta':float('inf'),'se':float('inf'),
            'bootstrap_p05_improvement':float('-inf'),'bootstrap_prob_improvement':0.0,
            'folds':len(cand)}
   delta=np.asarray(cand)-np.asarray(fixed)
   # Block bootstrap at the walk-forward-fold level. This preserves temporal
   # dependence better than row-wise resampling and estimates whether the
   # candidate's improvement over the fixed ensemble survives period variation.
   rng=np.random.default_rng(20260922)
   # Use a larger fold-level bootstrap while keeping the resampling unit
   # temporal (walk-forward folds), never individual rows.
   idx=rng.integers(0,len(delta),size=(1000,len(delta)))
   boot_delta=delta[idx].mean(axis=1)
   improvement=-boot_delta
   return {'mean_delta':float(delta.mean()),'std_delta':float(delta.std(ddof=1)),
           'se':float(delta.std(ddof=1)/np.sqrt(len(delta))),
           'bootstrap_p05_improvement':float(np.quantile(improvement,0.05)),
           'bootstrap_prob_improvement':float(np.mean(improvement>0.0)),
           'folds':len(delta)}

  # Search weighted pairs across the full model pool rather than only the
  # per-model top-4. A model can be mediocre alone yet add complementary signal
  # to the incumbent ensemble. Predictions are already cached, so this expands
  # ensemble coverage without adding model fits.
  weighted_pair_pool=list(dict.fromkeys(list(top_rank)+list(names)))
  weighted_candidates=[]
  for a,b in combinations(weighted_pair_pool,2):
   for wa in (0.20,0.30,0.40,0.50,0.60,0.70,0.80):
    weights={a:wa,b:1.0-wa}
    overall,robust,folds,wins=_weighted_candidate_score((a,b),weights)
    _,regime_excess,_=_regime_robust_objective((a,b),weights)
    robust += 0.15*regime_excess
    paired=_paired_fold_delta_stats((a,b),weights,fixed_models)
    block_deltas=_nonoverlap_block_deltas((a,b),weights,fixed_models)
    robust += max(0.0,paired['se'])
    if np.isfinite(paired.get('bootstrap_p05_improvement',float('-inf'))) and paired.get('bootstrap_p05_improvement',float('-inf')) <= 0.0:
     robust += 0.001 + abs(float(paired.get('bootstrap_p05_improvement',0.0)))
    weighted_candidates.append((robust,overall['logloss'],overall['brier'],overall['ece'],(a,b),weights,folds,paired,block_deltas))
  # Keep the 3-model search bounded: use the top-6 individual candidates,
  # while allowing all weights on that diversity shortlist.
  triple_pool=rank[:min(6,len(rank))]
  for spec in combinations(triple_pool,3):
   for wa in (0.20,0.30,0.40,0.50,0.60):
    for wb in (0.20,0.30,0.40,0.50,0.60):
     wc=1.0-wa-wb
     if wc < 0.20 or wc > 0.60: continue
     weights={spec[0]:wa,spec[1]:wb,spec[2]:wc}
     overall,robust,folds,wins=_weighted_candidate_score(spec,weights)
     _,regime_excess,_=_regime_robust_objective(spec,weights)
     robust += 0.15*regime_excess
     paired=_paired_fold_delta_stats(spec,weights,fixed_models)
     block_deltas=_nonoverlap_block_deltas(spec,weights,fixed_models)
     robust += max(0.0,paired['se'])
     weighted_candidates.append((robust,overall['logloss'],overall['brier'],overall['ece'],spec,weights,folds,paired,block_deltas))
  if weighted_candidates:
   weighted_candidates.sort(key=lambda z:(z[0],z[2],z[3]))
   wc=weighted_candidates[0]
   weighted_robust=wc[0]
   paired=wc[7] if len(wc)>7 else {'mean_delta':0.0,'se':float('inf'),'folds':0}
   block_deltas=wc[8] if len(wc)>8 else []
   block_improvement_count=sum(1 for d in block_deltas if d < 0.0)
   allowed_block_degradation=max(0.001,0.005*float(fixed_oos_metric['logloss']))
   if (paired.get('folds',0) >= 6
       and len(block_deltas) >= 3
       and block_improvement_count >= 2
       and max(block_deltas) <= allowed_block_degradation
       and weighted_robust + 0.0002 < fixed_oos_metric['robust_objective']
       and paired['mean_delta'] < -max(0.0002, paired['se'] if np.isfinite(paired['se']) else 0.0)
       and paired.get('bootstrap_p05_improvement',float('-inf')) > 0.0
       and paired.get('bootstrap_prob_improvement',0.0) >= 0.90):
    spec=tuple(wc[4])
    cand_weights=dict(wc[5])
    wa_metric={'logloss':wc[1],'brier':wc[2],'ece':wc[3],'robust_objective':weighted_robust,'fold_logloss_std':float(np.std(wc[6])) if wc[6] else float('inf'),'paired_oos_folds':int(paired['folds']),'paired_delta_mean':float(paired['mean_delta']),'paired_delta_se':float(paired['se']), 'paired_bootstrap_p05_improvement':float(paired.get('bootstrap_p05_improvement',float('-inf'))), 'paired_bootstrap_prob_improvement':float(paired.get('bootstrap_prob_improvement',0.0)),
     'nonoverlap_block_deltas':list(map(float,block_deltas)),
     'nonoverlap_block_improvement_count':int(block_improvement_count),
     'allowed_block_degradation':float(allowed_block_degradation)}
    wa_a=spec[0];wa_b=spec[1];wa_weight=float(cand_weights[wa_a])
    wa_win_rate=float(np.mean([1.0 if d <= fixed_oos_metric['logloss'] else 0.0 for d in wc[6]])) if wc[6] else 0.0
    wa_mean_delta=float(fixed_oos_metric['logloss']-wc[1])
    wa_fold_std=float(np.std(wc[6])) if wc[6] else float('inf')
    wa_robust_gain=float(fixed_oos_metric['robust_objective']-weighted_robust)
    best=spec
    candidate_label='weighted_ensemble'
    candidate_weights=cand_weights

  final_pool=base.pool(fs, symmetric=symmetric_mode)
  models=[]
  for name in best:
   m=final_pool[name]
   m.fit(X,y)
   models.append(m)
  hold_p=np.sum(np.column_stack([models[i].predict_proba(X_holdout)[:,1]*candidate_weights[name] for i,name in enumerate(best)]),axis=1)
  hold=base.metric(y_holdout,hold_p)
  hold['models']=list(best)
  hold['candidate_strategy']=candidate_label
  hold['candidate_weights']=candidate_weights
  selected_oos_metric = wa_metric if candidate_label=='weighted_ensemble' and wa_metric is not None else fixed_oos_metric
  selected_oos_p = np.asarray(
   np.sum(np.column_stack([np.asarray(oof_probs[n],float)*candidate_weights[n] for n in best]),axis=1),
   dtype=float
  )
  calibration=_temporal_calibration_candidate(selected_oos_p,oof_y)
  probability_calibrator=calibration.get('model') if calibration.get('accepted') else None
  if probability_calibrator is not None:
   raw_hold_p=np.asarray(
    np.sum(np.column_stack([np.asarray(models[i].predict_proba(X_holdout)[:,1])*candidate_weights[name] for i,name in enumerate(best)]),axis=1),
    dtype=float
   )
   if calibration.get('method')=='sigmoid':
    z_hold=np.log(np.clip(raw_hold_p,1e-6,1-1e-6)/(1.0-np.clip(raw_hold_p,1e-6,1-1e-6))).reshape(-1,1)
    calibrated_hold_p=np.clip(probability_calibrator.predict_proba(z_hold)[:,1],1e-6,1-1e-6)
   elif calibration.get('method')=='beta':
    bp_hold=np.column_stack([np.log(np.clip(raw_hold_p,1e-6,1-1e-6)),np.log(1.0-np.clip(raw_hold_p,1e-6,1-1e-6))])
    calibrated_hold_p=np.clip(probability_calibrator.predict_proba(bp_hold)[:,1],1e-6,1-1e-6)
   else:
    calibrated_hold_p=np.clip(probability_calibrator.predict(raw_hold_p),1e-6,1-1e-6)
   hold_probability_calibrated=base.metric(y_holdout,calibrated_hold_p)
   hold_probability_calibrated['models']=list(best)
   hold_probability_calibrated['candidate_strategy']=candidate_label
   hold_probability_calibrated['candidate_weights']=candidate_weights
   hold_probability_calibrated['calibration_applied']=True
   hold=hold_probability_calibrated
  else:
   hold['calibration_applied']=False
  if hold['ece']>.20:return _write_result(s,{'sport':s,'status':'REJECTED_HOLDOUT_CALIBRATION','holdout_metrics':hold,'selection_oos':oos,'ensemble_selection':scores})
  old=None;r=c.execute("SELECT metadata_json FROM model_state_snapshot WHERE sport=? AND market='winner' ORDER BY as_of_utc DESC LIMIT 1",(s,)).fetchone()
  if r:
   try:old=json.loads(r[0]).get('holdout_metrics')
   except Exception:old=None
  old_registry_hash=(previous or {}).get('frozen_holdout_registry_hash') if isinstance(previous,dict) else None
  if old and 'logloss' in old and old_registry_hash==registry['registry_hash']:
   old_ll=float(old['logloss']); old_brier=float(old.get('brier',hold['brier'])); old_ece=float(old.get('ece',hold['ece']))
   tol=max(.002,.01*old_ll)
   ll_improvement=old_ll-hold['logloss']
   brier_guard=hold['brier'] <= old_brier + .01
   ece_guard=hold['ece'] <= max(.20,old_ece + .03)
   if ll_improvement < tol or not brier_guard or not ece_guard:
    return _write_result(s,{'sport':s,'status':'REJECTED_CHALLENGER','reason':f"new_ll={hold['logloss']:.6f};old_ll={old_ll:.6f};improvement={ll_improvement:.6f};required={tol:.6f};brier_guard={brier_guard};ece_guard={ece_guard}",'holdout_metrics':hold,'selection_oos':oos,'ensemble_selection':scores})
  # Challenger-only dynamic routing. It is evaluated against the exact selected
  # incumbent ensemble, not a different equal-weight model pool.
  # A single-model incumbent has no routing surface and therefore keeps the fixed model.
  # Always materialize frozen-holdout component predictions for downstream
  # research layers. This is safe for production because the predictions are
  # derived from the already-selected production candidate and do not alter it.
  router_holdout_pred={name:np.clip(model.predict_proba(X_holdout)[:,1],1e-6,1-1e-6) for name,model in zip(best,models)}
  router_names=list(best) if len(best)>=2 else []
  if router_names:
   router_eval=router.evaluate_router_from_folds(X,y,router_names,oof_folds,sel,base.metric,candidate_weights)
   router_holdout_models={name:model for name,model in zip(best,models)}
   router_holdout_pred={name:np.clip(router_holdout_models[name].predict_proba(X_holdout)[:,1],1e-6,1-1e-6) for name in router_names}
   router_holdout=router.evaluate_frozen_holdout_router_from_folds(X,y,router_names,oof_folds,sel,router_holdout_pred,X_holdout,y_holdout,candidate_weights)
  else:
   router_eval={'status':'DISABLED_SINGLE_MODEL_BASELINE','reason':'selected_incumbent_has_one_model; dynamic routing cannot add diversification'}
   router_holdout={'status':'DISABLED_SINGLE_MODEL_BASELINE','reason':'selected_incumbent_has_one_model; frozen-holdout router comparison not applicable'}

  recent_weighted_eval=evaluate_recent_weighted_router_from_folds(X,y,router_names if router_names else list(best),oof_folds,candidate_weights)
  recent_weighted_holdout=evaluate_recent_weighted_router_holdout_from_folds(
   X,y,router_names if router_names else list(best),oof_folds,router_holdout_pred,X_holdout,y_holdout,candidate_weights
  ) if router_names else {'status':'DISABLED_SINGLE_MODEL_BASELINE','reason':'selected incumbent has one model'}
  recent_block_deltas=list(recent_weighted_eval.get('nonoverlap_block_deltas') or [])
  recent_block_improvements=sum(1 for d in recent_block_deltas if float(d)<0.0)
  recent_allowed_block_degradation=max(.001,.005*float(selected_oos_metric['logloss']))
  recent_weighted_accept=(
   recent_weighted_eval.get('status')=='EVALUATED'
   and recent_weighted_eval.get('folds',0)>=6
   and len(recent_block_deltas)>=3
   and recent_block_improvements>=2
   and max(recent_block_deltas)<=recent_allowed_block_degradation
   and recent_weighted_eval.get('logloss_improvement',-1.0)>=max(.001,.005*selected_oos_metric['logloss'])
   and recent_weighted_eval.get('brier_improvement',-1.0)>=-.002
   and recent_weighted_eval.get('ece_change',1.0)<=.02
   and recent_weighted_eval.get('bootstrap_p05_improvement',float('-inf'))>0.0
   and recent_weighted_eval.get('bootstrap_prob_improvement',0.0)>=.90
  )
  recent_weighted_eval['promotion_status']='RESEARCH_ONLY_NO_AUTO_PROMOTION'
  recent_weighted_eval['accepted_for_research_comparison']=bool(recent_weighted_accept)
  # Research-only selective case-risk layer. It predicts whether the
  # incumbent ensemble will be wrong without modifying its probability.
  case_risk_eval = case_risk.evaluate_selective_case_risk_oof(
   y, router_names if router_names else list(best), oof_folds, candidate_weights
  )
  case_risk_holdout = {'status':'DISABLED_SINGLE_MODEL_BASELINE','reason':'selected incumbent has one model'}
  case_risk_status = 'RESEARCH_ONLY_NO_AUTO_PROMOTION'
  case_risk_bundle = None
  if case_risk_eval.get('status') == 'EVALUATED':
   risk_names = router_names if router_names else list(best)
   case_risk_bundle = case_risk.fit_final_case_risk_model(y, risk_names, oof_folds, candidate_weights)
   if case_risk_bundle is not None:
    hold_bp_risk = np.column_stack([np.clip(router_holdout_pred[name],1e-6,1-1e-6) for name in risk_names]) if risk_names else np.empty((len(y_holdout),0))
    hold_base_risk = np.sum(hold_bp_risk*np.asarray([candidate_weights[name] for name in risk_names])[None,:],axis=1) if risk_names else np.full(len(y_holdout),0.5)
    holdout_population_ctx_risk = np.repeat(uncertainty_router.population_drift_features(X,X_holdout)[None,:],len(X_holdout),axis=0)
    hold_risk_ctx = np.column_stack([router._context(X,X_holdout),matchday_holdout_ctx,holdout_population_ctx_risk])
    risk_hold = case_risk.predict_case_risk(case_risk_bundle,hold_bp_risk,hold_risk_ctx)
    hold_err = ((hold_base_risk >= 0.5).astype(int) != y_holdout).astype(int)
    hold_base_risk_score = np.clip(1.0-np.abs(hold_base_risk-0.5)*2.0,1e-6,1.0-1e-6)
    case_risk_holdout = {
     'status':'EVALUATED','holdout_rows':int(len(y_holdout)),
     'fixed_ensemble_error_rate':float(np.mean(hold_err)),
     'risk_auc':case_risk._safe_auc(hold_err,risk_hold),
     'risk_average_precision':case_risk._safe_ap(hold_err,risk_hold),
     'baseline_confidence_auc':case_risk._safe_auc(hold_err,hold_base_risk_score),
     'risk_coverage':case_risk._risk_coverage(hold_err,risk_hold),
     'baseline_confidence_coverage':case_risk._risk_coverage(hold_err,hold_base_risk_score),
     'aurc':case_risk._aurc(hold_err,risk_hold),
     'baseline_confidence_aurc':case_risk._aurc(hold_err,hold_base_risk_score),
    }
    case_risk_holdout['auc_improvement'] = None if case_risk_holdout['risk_auc'] is None or case_risk_holdout['baseline_confidence_auc'] is None else float(case_risk_holdout['risk_auc']-case_risk_holdout['baseline_confidence_auc'])
    case_risk_holdout['aurc_improvement'] = float(case_risk_holdout['baseline_confidence_aurc']-case_risk_holdout['aurc'])
    oos_auc_gain = case_risk_eval.get('auc_improvement')
    oos_aurc_gain = case_risk_eval.get('aurc_improvement')
    oos_relative_aurc = float(oos_aurc_gain/max(abs(float(case_risk_eval.get('baseline_confidence_aurc',0.0))),1e-9)) if oos_aurc_gain is not None else 0.0
    hold_auc_gain = case_risk_holdout.get('auc_improvement')
    hold_aurc_gain = case_risk_holdout.get('aurc_improvement')
    case_risk_eval['relative_aurc_improvement_vs_baseline_confidence']=oos_relative_aurc
    case_risk_holdout['oos_auc_improvement']=oos_auc_gain
    case_risk_holdout['oos_relative_aurc_improvement']=oos_relative_aurc
    case_risk_accept=bool(
     case_risk_eval.get('folds',0)>=6
     and case_risk_eval.get('crossfit_folds_with_trained_risk_model',0)>=4
     and oos_auc_gain is not None and float(oos_auc_gain)>=0.02
     and oos_relative_aurc>=0.03
     and hold_auc_gain is not None and float(hold_auc_gain)>=0.0
     and hold_aurc_gain is not None and float(hold_aurc_gain)>=0.0
    )
    case_risk_eval['accepted_for_research_comparison']=case_risk_accept
    case_risk_holdout['accepted_for_research_comparison']=case_risk_accept
    if case_risk_accept: case_risk_status='RESEARCH_ACCEPTED_PENDING_PRODUCTION_POLICY'
   else:
    case_risk_eval['accepted_for_research_comparison']=False
  else:
   case_risk_eval['accepted_for_research_comparison']=False
  case_risk_eval['promotion_status']=case_risk_status
  case_risk_holdout['promotion_status']=case_risk_status

  # Research-only next generation: uncertainty/disagreement/drift-aware routing
  # followed by a separate temporal recalibration layer. It never changes the
  # incumbent artifact directly; release remains controlled by the existing gate.
  uncertainty_eval={'status':'DISABLED_SINGLE_MODEL_BASELINE','reason':'selected incumbent has one model'}
  uncertainty_holdout={'status':'DISABLED_SINGLE_MODEL_BASELINE','reason':'selected incumbent has one model'}
  uncertainty_calibration={'accepted':False,'method':'none','reason':'not_evaluated'}
  uncertainty_accept=False
  uncertainty_recency_eval={'status':'NOT_EVALUATED','selector_recency_half_life':720.0}
  uncertainty_recency_holdout={'status':'NOT_EVALUATED','selector_recency_half_life':720.0}
  uncertainty_recency_calibration={'accepted':False,'method':'none','reason':'not_evaluated'}
  uncertainty_recency_accept=False
  if router_names:
   uncertainty_eval=uncertainty_router.evaluate_oof(
    X,y,router_names,oof_folds,candidate_weights,base.metric
   )
   raw_oof=uncertainty_eval.get('oof_routed_predictions') or []
   oof_target=np.asarray(uncertainty_eval.get('oof_targets') or [],dtype=int)
   if uncertainty_eval.get('status')=='EVALUATED' and len(raw_oof)==len(oof_target) and len(raw_oof)>=180:
    uncertainty_calibration=uncertainty_router.temporal_recalibration(
     np.asarray(raw_oof,dtype=float),oof_target,np.asarray(oof_event_ids,dtype=object)
    )
    # Build the final research-only selector from all pre-holdout OOF folds.
    u_selector,u_history,u_oof_rows=uncertainty_router.fit_final_selector_from_folds(
     X,y,router_names,oof_folds,candidate_weights
    )
    hold_bp=np.column_stack([
     np.clip(router_holdout_pred[name],1e-6,1-1e-6) for name in router_names
    ])
    hold_baseline=np.sum(
     hold_bp*np.asarray([candidate_weights[name] for name in router_names])[None,:],
     axis=1
    )
    holdout_population_drift=uncertainty_router.population_drift_features(X,X_holdout)
    holdout_population_ctx=np.repeat(holdout_population_drift[None,:],len(X_holdout),axis=0)
    hold_ctx=np.column_stack([
     router._context(X,X_holdout),
     matchday_holdout_ctx,
     holdout_population_ctx
    ])
    raw_hold_unc=uncertainty_router.route_with_selector(
     u_selector,u_history,hold_bp,hold_ctx,hold_baseline
    )
    calibrated_hold_unc=uncertainty_router.apply_recalibration(
     raw_hold_unc,uncertainty_calibration
    )
    raw_hold_metrics=base.metric(y_holdout,raw_hold_unc)
    calibrated_hold_metrics=base.metric(y_holdout,calibrated_hold_unc)
    uncertainty_holdout={
     'status':'EVALUATED',
     'holdout_rows':int(len(y_holdout)),
     'oos_training_rows':int(u_oof_rows),
     'fixed_ensemble':base.metric(y_holdout,hold_baseline),
     'uncertainty_router_raw':raw_hold_metrics,
     'uncertainty_router_recalibrated':calibrated_hold_metrics,
     'raw_logloss_improvement':float(base.metric(y_holdout,hold_baseline)['logloss']-raw_hold_metrics['logloss']),
     'recalibrated_logloss_improvement':float(base.metric(y_holdout,hold_baseline)['logloss']-calibrated_hold_metrics['logloss']),
     'calibration_accepted_pre_holdout':bool(uncertainty_calibration.get('accepted')),
     'calibration_method':str(uncertainty_calibration.get('method') or 'none'),
    }
    fold_deltas=np.asarray(uncertainty_eval.get('fold_logloss_deltas') or [],dtype=float)
    block_deltas=[]
    if len(fold_deltas)>=3:
     for ids in np.array_split(np.arange(len(fold_deltas)),3):
      if len(ids):
       block_deltas.append(float(np.mean(fold_deltas[ids])))
    uncertainty_eval['nonoverlap_block_deltas']=block_deltas
    uncertainty_eval['nonoverlap_block_improvement_count']=int(sum(1 for d in block_deltas if d<0.0))
    uncertainty_eval['bootstrap']=uncertainty_router.bootstrap_fold_improvement(fold_deltas)
    uncertainty_allowed=max(.001,.005*float(selected_oos_metric['logloss']))
    uncertainty_accept=(
     uncertainty_eval.get('status')=='EVALUATED'
     and uncertainty_eval.get('folds',0)>=6
     and len(block_deltas)>=3
     and uncertainty_eval['nonoverlap_block_improvement_count']>=2
     and max(block_deltas)<=uncertainty_allowed
     and uncertainty_eval.get('logloss_improvement',-1.0)>=uncertainty_allowed
     and uncertainty_eval.get('brier_improvement',-1.0)>=-.002
     and uncertainty_eval.get('ece_change',1.0)<=.02
     and uncertainty_eval['bootstrap'].get('p05_improvement',float('-inf'))>0.0
     and uncertainty_eval['bootstrap'].get('probability_improvement',0.0)>=.90
     and uncertainty_calibration.get('accepted') is True
    )

    # Research-only drift-adaptive candidate: recency-weight the selector's
    # pre-holdout OOF training data. The incumbent uncertainty router remains
    # untouched; this branch is evaluated independently and is never auto-promoted.
    uncertainty_recency_eval=uncertainty_router.evaluate_oof(
     X,y,router_names,oof_folds,candidate_weights,base.metric,selector_recency_half_life=720.0
    )
    rr_oof=uncertainty_recency_eval.get('oof_routed_predictions') or []
    rr_target=np.asarray(uncertainty_recency_eval.get('oof_targets') or [],dtype=int)
    if uncertainty_recency_eval.get('status')=='EVALUATED' and len(rr_oof)==len(rr_target) and len(rr_oof)>=180:
     uncertainty_recency_calibration=uncertainty_router.temporal_recalibration(
      np.asarray(rr_oof,dtype=float),rr_target,np.asarray(oof_event_ids,dtype=object)
     )
     rr_selector,rr_history,rr_oof_rows=uncertainty_router.fit_final_selector_from_folds(
      X,y,router_names,oof_folds,candidate_weights,selector_recency_half_life=720.0
     )
     rr_hold_raw=uncertainty_router.route_with_selector(
      rr_selector,rr_history,hold_bp,hold_ctx,hold_baseline
     )
     rr_hold_cal=uncertainty_router.apply_recalibration(
      rr_hold_raw,uncertainty_recency_calibration
     )
     rr_hold_raw_m=base.metric(y_holdout,rr_hold_raw)
     rr_hold_cal_m=base.metric(y_holdout,rr_hold_cal)
     rr_fixed_m=base.metric(y_holdout,hold_baseline)
     uncertainty_recency_holdout={
      'status':'EVALUATED',
      'holdout_rows':int(len(y_holdout)),
      'oos_training_rows':int(rr_oof_rows),
      'fixed_ensemble':rr_fixed_m,
      'uncertainty_router_raw':rr_hold_raw_m,
      'uncertainty_router_recalibrated':rr_hold_cal_m,
      'raw_logloss_improvement':float(rr_fixed_m['logloss']-rr_hold_raw_m['logloss']),
      'recalibrated_logloss_improvement':float(rr_fixed_m['logloss']-rr_hold_cal_m['logloss']),
      'calibration_accepted_pre_holdout':bool(uncertainty_recency_calibration.get('accepted')),
      'calibration_method':str(uncertainty_recency_calibration.get('method') or 'none'),
      'selector_recency_half_life':720.0,
     }
     rr_deltas=np.asarray(uncertainty_recency_eval.get('fold_logloss_deltas') or [],dtype=float)
     rr_blocks=[]
     if len(rr_deltas)>=3:
      for ridx in np.array_split(np.arange(len(rr_deltas)),3):
       if len(ridx): rr_blocks.append(float(np.mean(rr_deltas[ridx])))
     uncertainty_recency_eval['nonoverlap_block_deltas']=rr_blocks
     uncertainty_recency_eval['nonoverlap_block_improvement_count']=int(sum(1 for d in rr_blocks if d<0.0))
     uncertainty_recency_eval['bootstrap']=uncertainty_router.bootstrap_fold_improvement(rr_deltas)
     rr_allowed=max(.001,.005*float(selected_oos_metric['logloss']))
     uncertainty_recency_accept=bool(
      uncertainty_recency_eval.get('status')=='EVALUATED'
      and uncertainty_recency_eval.get('folds',0)>=6
      and len(rr_blocks)>=3
      and uncertainty_recency_eval['nonoverlap_block_improvement_count']>=2
      and max(rr_blocks)<=rr_allowed
      and uncertainty_recency_eval.get('logloss_improvement',-1.0)>=rr_allowed
      and uncertainty_recency_eval.get('brier_improvement',-1.0)>=-.002
      and uncertainty_recency_eval.get('ece_change',1.0)<=.02
      and uncertainty_recency_eval['bootstrap'].get('p05_improvement',float('-inf'))>0.0
      and uncertainty_recency_eval['bootstrap'].get('probability_improvement',0.0)>=.90
      and uncertainty_recency_calibration.get('accepted') is True
      and rr_holdout.get('raw_logloss_improvement',-1.0)>=0.0
      and rr_holdout.get('recalibrated_logloss_improvement',-1.0)>=0.0
     )
    uncertainty_recency_eval['promotion_status']='RESEARCH_ONLY_NO_AUTO_PROMOTION'
    uncertainty_recency_eval['accepted_for_research_comparison']=bool(uncertainty_recency_accept)
   else:
    uncertainty_recency_eval={'status':'INSUFFICIENT_OOS','reason':'recency-weighted selector could not form auditable pre-holdout OOF sample','selector_recency_half_life':720.0}
    uncertainty_recency_holdout={'status':'INSUFFICIENT_OOS','selector_recency_half_life':720.0}

   else:
    uncertainty_eval={'status':'INSUFFICIENT_OOS', 'reason':'uncertainty router could not form auditable pre-holdout OOF sample'}
  # Never serialize raw OOF prediction vectors into the committed research JSON.
  uncertainty_recency_eval.pop('oof_targets',None)
  uncertainty_recency_eval.pop('oof_static_predictions',None)
  uncertainty_recency_eval.pop('oof_routed_predictions',None)
  uncertainty_recency_eval.setdefault('promotion_status','RESEARCH_ONLY_NO_AUTO_PROMOTION')
  uncertainty_recency_eval.setdefault('accepted_for_research_comparison',bool(uncertainty_recency_accept))
  uncertainty_eval.pop('oof_targets',None)
  uncertainty_eval.pop('oof_static_predictions',None)
  uncertainty_eval.pop('oof_routed_predictions',None)
  uncertainty_eval['promotion_status']='RESEARCH_ONLY_NO_AUTO_PROMOTION'
  uncertainty_eval['accepted_for_research_comparison']=bool(uncertainty_accept)
  uncertainty_calibration_summary={k:v for k,v in uncertainty_calibration.items() if k!='model'}
  # Promotion is decided from pre-holdout chronological OOS only.
  # The frozen holdout is strictly score-only and must never affect routing adoption.
  router_block_deltas=list(router_eval.get('nonoverlap_block_deltas') or [])
  router_block_improvements=sum(1 for d in router_block_deltas if float(d) < 0.0)
  router_allowed_block_degradation=max(.001,.005*float(selected_oos_metric['logloss']))
  router_accept = (router_eval.get('status') == 'EVALUATED'
                   and router_eval.get('folds',0) >= 6
                   and len(router_block_deltas) >= 3
                   and router_block_improvements >= 2
                   and max(router_block_deltas) <= router_allowed_block_degradation
                   and router_eval['logloss_improvement'] >= max(.001,.005*selected_oos_metric['logloss'])
                   and router_eval['brier_improvement'] >= -.002
                   and router_eval['ece_change'] <= .02
                   and router_eval.get('bootstrap_p05_improvement',float('-inf')) > 0.0
                   and router_eval.get('bootstrap_prob_improvement',0.0) >= 0.90)
  final_router=None
  router_models_artifact={}
  router_feature_reference=None
  if router_accept:
   final_router=router.fit_final_router_from_folds(X,y,router_names,oof_folds,sel,candidate_weights)
   if final_router is None:
    router_accept=False
   else:
    for name in router_names:
     m=final_pool[name]
     m.fit(X[:sel],y[:sel])
     router_models_artifact[name]=m
    router_feature_reference=router.context_reference(X[:sel])
  ver=h({'sport':s,'features':fs,'models':best,'oos':oos,'ensemble_selection':scores,'holdout':hold,'router':router_eval,'router_holdout':router_holdout,'router_accept':router_accept,'uncertainty_router':uncertainty_eval,'uncertainty_holdout':uncertainty_holdout,'uncertainty_calibration':uncertainty_calibration_summary,'uncertainty_recency':uncertainty_recency_eval,'uncertainty_recency_holdout':uncertainty_recency_holdout,'cutoff':train_rows[-1][1],'frozen_holdout_registry_hash':registry['registry_hash']});MODELS.mkdir(parents=True,exist_ok=True);RESULTS.mkdir(parents=True,exist_ok=True);path=MODELS/f'{s}_current.joblib';joblib.dump({'quality_status':'ACCEPTED_LOCKED_HOLDOUT','models':models,'model_names':list(best),'ensemble_weights':candidate_weights,'ensemble_strategy':candidate_label,'probability_calibrator':probability_calibrator,'features':fs,'sport':s,'model_version':ver,'training_rows':sel,'frozen_holdout_rows':hn,'frozen_holdout_registry_hash':registry['registry_hash'],'dynamic_router':final_router if router_accept else None,'dynamic_router_names':router_names if router_accept else [],'dynamic_router_models':router_models_artifact if router_accept else {},'dynamic_router_feature_reference':router_feature_reference,'dynamic_router_status':'PRODUCTION_ROUTABLE_AFTER_GATES' if router_accept else 'FALLBACK_FIXED_ENSEMBLE','dynamic_router_eval':router_eval,'dynamic_router_holdout_eval':router_holdout,'probability_calibration':calibration,'case_risk_status':case_risk_status,'case_risk_model':case_risk_bundle if case_risk_eval.get('accepted_for_research_comparison') else None},path)
  sha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip();meta={'sport':s,'market':'winner','model_version':ver,'feature_version':'strict-pit-v19-multiscale-form-h2h-freshness-router-competition-elo-features','training_cutoff_utc':rows[sel-1][1],'git_commit_sha':sha,'artifact_path':str(path.relative_to(ROOT)),'quality_status':'ACCEPTED_LOCKED_HOLDOUT','selection_models':list(best),'ensemble_weights':candidate_weights,'ensemble_strategy':candidate_label,'selection_oos':oos,'ensemble_selection':scores,'weighted_pair_oos':wa_metric,'weighted_pair_win_rate':wa_win_rate,'weighted_pair_mean_delta':wa_mean_delta,'weighted_pair_fold_delta_std':wa_fold_std,'weighted_pair_robust_gain':wa_robust_gain,'weighted_pair_oos':wa_metric,'holdout_metrics':hold,'frozen_holdout_registry_hash':registry['registry_hash'],'probability_calibration':{k:v for k,v in calibration.items() if k!='model'},'holdout_frozen':True,'production_fit_excludes_holdout':True,'frozen_holdout_registry_hash':registry['registry_hash'],'dynamic_router':router_eval,'dynamic_router_holdout':router_holdout,'dynamic_router_status':'PRODUCTION_ROUTABLE_AFTER_GATES' if router_accept else 'FALLBACK_FIXED_ENSEMBLE'}
  c.execute('INSERT INTO model_state_snapshot(snapshot_id,sport,market,as_of_utc,model_version,feature_version,training_cutoff_utc,dataset_hash,git_commit_sha,artifact_path,quality_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(h(meta),s,'winner',utc(),ver,meta['feature_version'],rows[sel-1][1],h([(r[0],r[1],r[2]) for r in train_rows]),sha,str(path.relative_to(ROOT)),'ACCEPTED_LOCKED_HOLDOUT',json.dumps(meta,ensure_ascii=False)));c.commit()
  out={'sport':s,'status':'TRAINED','models':list(best),'model_version':ver,'feature_version':meta['feature_version'],'training_rows':sel,'frozen_holdout_rows':hn,'features':len(fs),'training_cutoff_utc':meta['training_cutoff_utc'],'git_commit_sha':sha,'artifact_path':meta['artifact_path'],'selection_oos':oos,'ensemble_selection':scores,'holdout_metrics':hold,'probability_calibration':{k:v for k,v in calibration.items() if k!='model'},'holdout_frozen':True,'production_fit_excludes_holdout':True,'dynamic_router':router_eval,'dynamic_router_holdout':router_holdout,'dynamic_router_status':('RESEARCH_ONLY_HOLDOUT_PASS_PENDING_PROMOTION' if router_accept else 'FALLBACK_FIXED_ENSEMBLE'),'uncertainty_router':uncertainty_eval,'uncertainty_holdout':uncertainty_holdout,'uncertainty_calibration':uncertainty_calibration_summary,'uncertainty_recency':uncertainty_recency_eval,'uncertainty_recency_holdout':uncertainty_recency_holdout,'uncertainty_recency_calibration':{k:v for k,v in uncertainty_recency_calibration.items() if k!='model'},'case_risk_eval':case_risk_eval,'case_risk_holdout':case_risk_holdout,'case_risk_status':case_risk_status};return _write_result(s,out)
 finally:c.close()
def main():
 import argparse
 a=argparse.ArgumentParser();a.add_argument('--sport',choices=ALL_SPORTS);x=a.parse_args();print(json.dumps([train(s) for s in ([x.sport] if x.sport else SPORTS)],ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
