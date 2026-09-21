from __future__ import annotations
import hashlib,json,sqlite3,subprocess
from pathlib import Path
from itertools import combinations
import joblib,numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression
from src import research_cycle_v4 as base
from src import dynamic_model_router as router
ROOT=Path(__file__).resolve().parents[1];DB=ROOT/'data/db/sports_v45.sqlite';MODELS=ROOT/'models/research';RESULTS=ROOT/'results/research'
SPORTS=('valorant','basketball','volleyball','ufc','rizin')
def utc():
 from datetime import datetime,timezone
 return datetime.now(timezone.utc).isoformat()
def h(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()[:16]
def f1():
 c=sqlite3.connect(DB)
 try:n=c.execute("select count(*) from event where sport='f1'").fetchone()[0];e=c.execute("select count(*) from source_snapshot where source='OpenF1' and availability_status='EXACT'").fetchone()[0]
 finally:c.close()
 return {'sport':'f1','status':'DEFERRED_PIT','events':int(n),'exact_pit_source_snapshots':int(e),'reason':'OpenF1 historical availability is not proven before the 60-minute cutoff; no leakage-prone proxy is permitted'}
def _temporal_calibration_candidate(p, y):
    """Choose none/sigmoid/beta/isotonic calibration using only pre-holdout OOS."""
    p=np.clip(np.asarray(p,dtype=float),1e-6,1-1e-6)
    y=np.asarray(y,int)
    if len(p)<120 or len(np.unique(y))<2:
        return {'accepted':False,'method':'none','reason':'insufficient_preholdout_oos_for_calibration'}
    cut=max(60,int(len(p)*0.70))
    if len(np.unique(y[:cut]))<2 or len(np.unique(y[cut:]))<2:
        return {'accepted':False,'method':'none','reason':'calibration_split_lacks_both_classes'}
    z=np.log(p/(1.0-p)).reshape(-1,1)
    raw=base.metric(y[cut:],p[cut:])
    candidates=[('none',None,raw)]
    sigmoid=LogisticRegression(C=0.25,max_iter=2000,random_state=42)
    sigmoid.fit(z[:cut],y[:cut])
    sp=np.clip(sigmoid.predict_proba(z[cut:])[:,1],1e-6,1-1e-6)
    candidates.append(('sigmoid',sigmoid,base.metric(y[cut:],sp)))
    # Beta calibration: logistic regression on log(p) and log(1-p).
    beta=np.column_stack([np.log(p),np.log(1.0-p)])
    beta_model=LogisticRegression(C=0.25,max_iter=2000,random_state=43)
    beta_model.fit(beta[:cut],y[:cut])
    bp=np.clip(beta_model.predict_proba(beta[cut:])[:,1],1e-6,1-1e-6)
    candidates.append(('beta',beta_model,base.metric(y[cut:],bp)))
    if len(p)>=300 and len(np.unique(p[:cut]))>=25:
        iso=IsotonicRegression(y_min=1e-6,y_max=1-1e-6,out_of_bounds='clip')
        iso.fit(p[:cut],y[:cut])
        ip=np.clip(iso.predict(p[cut:]),1e-6,1-1e-6)
        candidates.append(('isotonic',iso,base.metric(y[cut:],ip)))
    candidates.sort(key=lambda x:(x[2]['logloss'],x[2]['brier'],x[2]['ece']))
    method,model,score=candidates[0]
    required=max(0.001,0.003*raw['logloss'])
    accepted=(method!='none'
              and score['logloss']<=raw['logloss']-required
              and score['brier']<=raw['brier']+0.002
              and score['ece']<=raw['ece']+0.01)
    if not accepted:
        return {'accepted':False,'method':'none','reason':'preholdout_validation_did_not_pass','raw_validation':raw,
                'candidate_methods':{m:sc for m,_,sc in candidates},'required_logloss_improvement':required}
    if method=='sigmoid':
        final=LogisticRegression(C=0.25,max_iter=2000,random_state=42)
        final.fit(z,y)
    elif method=='beta':
        final=LogisticRegression(C=0.25,max_iter=2000,random_state=43)
        final.fit(np.column_stack([np.log(p),np.log(1.0-p)]),y)
    else:
        final=IsotonicRegression(y_min=1e-6,y_max=1-1e-6,out_of_bounds='clip')
        final.fit(p,y)
    return {'accepted':True,'method':method,'model':final,'raw_validation':raw,
            'calibrated_validation':score,'candidate_methods':{m:sc for m,_,sc in candidates},
            'required_logloss_improvement':required}


def _write_result(s, payload):
    """Persist every research outcome, including DEFERRED/REJECTED states."""
    RESULTS.mkdir(parents=True,exist_ok=True)
    (RESULTS/f'{s}.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
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
    if not (feature_version.startswith("strict-pit-v13-") or feature_version.startswith("strict-pit-v14-")):
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
               json.dumps(meta,ensure_ascii=False)))
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
  X=np.array([[r[3].get(f,np.nan) for f in fs] for r in rows]);y=np.array([r[2] for r in rows])
  # Never send all-missing columns into sklearn imputers. They carry no signal,
  # make feature schemas unstable across folds, and can trigger silent column drops.
  keep=np.isfinite(X).any(axis=0)
  if not keep.any():
   return _write_result(s,{'sport':s,'status':'DEFERRED','reason':'no_observed_feature_values','rows':len(rows),'features':0})
  fs=[f for f,k in zip(fs,keep) if k];X=X[:,keep]
  sel=int(len(rows)*.78);hn=len(rows)-sel
  if hn<30 or len(np.unique(y[sel:]))<2:return _write_result(s,{'sport':s,'status':'DEFERRED','reason':'insufficient_frozen_holdout','rows':len(rows),'holdout_rows':hn})
  names=list(base.pool())
  # Multi-window walk-forward OOS: reuse one common fold set to evaluate
  # several historical windows, reducing sensitivity to one arbitrary start.
  window_fracs=(0.55,0.60,0.65)
  window_starts=[max(60,int(sel*f)) for f in window_fracs]
  start=min(window_starts)
  step=max(10,min(30,int(sel*.06)))
  oof_probs={name:[] for name in names}
  oof_y=[]
  oof_folds=[]
  for end in range(start,sel,step):
   te=min(end+step,sel)
   if len(np.unique(y[:end]))<2:continue
   fold_pred={}
   for name in names:
    m=base.pool()[name]
    m.fit(X[:end],y[:end])
    fold_pred[name]=np.clip(m.predict_proba(X[end:te])[:,1],1e-6,1-1e-6)
    oof_probs[name].extend(fold_pred[name].tolist())
   oof_y.extend(y[end:te].tolist())
   oof_folds.append({'end':end,'te':te,'preds':fold_pred})
  oof_y=np.asarray(oof_y,int)
  if len(oof_y)<30 or len(np.unique(oof_y))<2:
   return _write_result(s,{'sport':s,'status':'DEFERRED','reason':'no_valid_walk_forward_folds','rows':len(rows)})
  def _window_metric_for_preds(pred_by_fold):
   out=[]
   for ws in window_starts:
    yy=[];pp=[]
    for fold in oof_folds:
     if int(fold['end'])<ws:continue
     yy.extend(y[int(fold['end']):int(fold['te'])].tolist())
     pp.extend(pred_by_fold[int(fold['end'])])
    if len(yy)>=20 and len(np.unique(yy))>1:
     out.append(base.metric(np.asarray(yy),np.asarray(pp)))
   return out
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
   window_scores=[]
   for ws in window_starts:
    yy=[];pp=[]
    for fold in oof_folds:
     if int(fold['end'])<ws:continue
     yy.extend(y[int(fold['end']):int(fold['te'])].tolist())
     fp=np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in spec])
     pp.extend(np.mean(fp,axis=1).tolist())
    if len(yy)>=20 and len(np.unique(yy))>1:
     window_scores.append(base.metric(np.asarray(yy),np.asarray(pp)))
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
    'competition_is_asian_games','competition_is_bleague','short_rest_flag',
    'games_last_7d','games_last_30d','recent_form_delta','elo_momentum'
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
     if rn in ('competition_is_asian_games','competition_is_bleague','short_rest_flag'):
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

  def _weighted_candidate_score(spec, weights):
   p_all=np.sum(np.column_stack([weights.get(n,0.0)*np.asarray(oof_probs[n],float) for n in spec]),axis=1)
   overall=base.metric(oof_y,p_all)
   fold_losses=[];window_scores=[]
   for ws in window_starts:
    yy=[];pp=[]
    for fold in oof_folds:
     if int(fold['end'])<ws:continue
     yy.extend(y[int(fold['end']):int(fold['te'])].tolist())
     fp=np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in spec])
     pp.extend(np.sum(fp*np.array([weights[n] for n in spec])[None,:],axis=1).tolist())
    if len(yy)>=20 and len(np.unique(yy))>1:
     window_scores.append(base.metric(np.asarray(yy),np.asarray(pp)))
   for fold in oof_folds:
    yy=y[int(fold['end']):int(fold['te'])]
    fp=np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in spec])
    pp=np.sum(fp*np.array([weights[n] for n in spec])[None,:],axis=1)
    if len(yy)>=20 and len(np.unique(yy))>1:
     fold_losses.append(base.metric(yy,pp)['logloss'])
   wl=np.asarray([m['logloss'] for m in window_scores],dtype=float)
   robust=float(np.average(wl,weights=np.array([0.20,0.30,0.50]))+0.10*np.std(wl)+0.05*np.std(fold_losses)) if len(window_scores)==3 else float(overall['logloss']+0.15*np.std(fold_losses))
   return overall,robust,fold_losses,window_scores

  weighted_candidates=[]
  for a,b in combinations(top_rank,2):
   for wa in (0.20,0.30,0.40,0.50,0.60,0.70,0.80):
    weights={a:wa,b:1.0-wa}
    overall,robust,folds,wins=_weighted_candidate_score((a,b),weights)
    _,regime_excess,_=_regime_robust_objective((a,b),weights)
    robust += 0.15*regime_excess
    weighted_candidates.append((robust,overall['logloss'],overall['brier'],overall['ece'],(a,b),weights,folds))
  for spec in combinations(top_rank[:4],3):
   for wa in (0.20,0.30,0.40,0.50,0.60):
    for wb in (0.20,0.30,0.40,0.50,0.60):
     wc=1.0-wa-wb
     if wc < 0.20 or wc > 0.60: continue
     weights={spec[0]:wa,spec[1]:wb,spec[2]:wc}
     overall,robust,folds,wins=_weighted_candidate_score(spec,weights)
     _,regime_excess,_=_regime_robust_objective(spec,weights)
     robust += 0.15*regime_excess
     weighted_candidates.append((robust,overall['logloss'],overall['brier'],overall['ece'],spec,weights,folds))
  if weighted_candidates:
   weighted_candidates.sort(key=lambda z:(z[0],z[2],z[3]))
   wc=weighted_candidates[0]
   weighted_robust=wc[0]
   if weighted_robust + 0.0002 < fixed_oos_metric['robust_objective']:
    spec=tuple(wc[4])
    cand_weights=dict(wc[5])
    wa_metric={'logloss':wc[1],'brier':wc[2],'ece':wc[3],'robust_objective':weighted_robust,'fold_logloss_std':float(np.std(wc[6])) if wc[6] else float('inf')}
    wa_a=spec[0];wa_b=spec[1];wa_weight=float(cand_weights[wa_a])
    wa_win_rate=float(np.mean([1.0 if d <= fixed_oos_metric['logloss'] else 0.0 for d in wc[6]])) if wc[6] else 0.0
    wa_mean_delta=float(fixed_oos_metric['logloss']-wc[1])
    wa_fold_std=float(np.std(wc[6])) if wc[6] else float('inf')
    wa_robust_gain=float(fixed_oos_metric['robust_objective']-weighted_robust)
    best=spec
    candidate_label='weighted_ensemble'
    candidate_weights=cand_weights

  models=[]
  for name in best:
   m=base.pool()[name]
   m.fit(X[:sel],y[:sel])
   models.append(m)
  hold_p=np.sum(np.column_stack([models[i].predict_proba(X[sel:])[:,1]*candidate_weights[name] for i,name in enumerate(best)]),axis=1)
  hold=base.metric(y[sel:],hold_p)
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
    np.sum(np.column_stack([np.asarray(models[i].predict_proba(X[sel:])[:,1])*candidate_weights[name] for i,name in enumerate(best)]),axis=1),
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
   hold_probability_calibrated=base.metric(y[sel:],calibrated_hold_p)
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
  if old and 'logloss' in old:
   old_ll=float(old['logloss']); old_brier=float(old.get('brier',hold['brier'])); old_ece=float(old.get('ece',hold['ece']))
   tol=max(.002,.01*old_ll)
   ll_improvement=old_ll-hold['logloss']
   brier_guard=hold['brier'] <= old_brier + .01
   ece_guard=hold['ece'] <= max(.20,old_ece + .03)
   if ll_improvement < tol or not brier_guard or not ece_guard:
    return _write_result(s,{'sport':s,'status':'REJECTED_CHALLENGER','reason':f"new_ll={hold['logloss']:.6f};old_ll={old_ll:.6f};improvement={ll_improvement:.6f};required={tol:.6f};brier_guard={brier_guard};ece_guard={ece_guard}",'holdout_metrics':hold,'selection_oos':oos,'ensemble_selection':scores})
  # Challenger-only dynamic routing. It is evaluated on chronological OOS before the frozen holdout.
  # The router can never promote itself from OOS alone; the incumbent remains the safe fallback.
  router_names=list(rank[:4])
  router_eval=router.evaluate_router_from_folds(X,y,router_names,oof_folds,sel,base.metric)
  router_holdout_models={name:model for name,model in zip(best,models)}
  for name in router_names:
   if name not in router_holdout_models:
    m=base.pool()[name]
    m.fit(X[:sel],y[:sel])
    router_holdout_models[name]=m
  router_holdout_pred={name:np.clip(router_holdout_models[name].predict_proba(X[sel:])[:,1],1e-6,1-1e-6) for name in router_names}
  router_holdout=router.evaluate_frozen_holdout_router_from_folds(X,y,router_names,oof_folds,sel,router_holdout_pred)
  router_accept = (router_eval.get('status') == 'EVALUATED'
                   and router_holdout.get('status') == 'EVALUATED'
                   and router_eval['logloss_improvement'] >= max(.001,.005*selected_oos_metric['logloss'])
                   and router_eval['brier_improvement'] >= -.002
                   and router_eval['ece_change'] <= .02
                   and router_holdout['logloss_improvement'] >= max(.001,.005*selected_oos_metric['logloss'])
                   and router_holdout['brier_improvement'] >= -.002
                   and router_holdout['ece_change'] <= .02)
  final_router=None
  router_models_artifact={}
  router_feature_reference=None
  if router_accept:
   final_router=router.fit_final_router_from_folds(X,y,router_names,oof_folds,sel)
   if final_router is None:
    router_accept=False
   else:
    for name in router_names:
     m=base.pool()[name]
     m.fit(X[:sel],y[:sel])
     router_models_artifact[name]=m
    router_feature_reference=router.context_reference(X[:sel])
  ver=h({'sport':s,'features':fs,'models':best,'oos':oos,'ensemble_selection':scores,'holdout':hold,'router':router_eval,'router_holdout':router_holdout,'router_accept':router_accept,'cutoff':rows[sel-1][1]});MODELS.mkdir(parents=True,exist_ok=True);RESULTS.mkdir(parents=True,exist_ok=True);path=MODELS/f'{s}_current.joblib';joblib.dump({'quality_status':'ACCEPTED_LOCKED_HOLDOUT','models':models,'model_names':list(best),'ensemble_weights':candidate_weights,'ensemble_strategy':candidate_label,'probability_calibrator':probability_calibrator,'features':fs,'sport':s,'model_version':ver,'training_rows':sel,'frozen_holdout_rows':hn,'dynamic_router':final_router if router_accept else None,'dynamic_router_names':router_names if router_accept else [],'dynamic_router_models':router_models_artifact if router_accept else {},'dynamic_router_feature_reference':router_feature_reference,'dynamic_router_status':'PRODUCTION_ROUTABLE_AFTER_GATES' if router_accept else 'FALLBACK_FIXED_ENSEMBLE','dynamic_router_eval':router_eval,'dynamic_router_holdout_eval':router_holdout,'probability_calibration':calibration},path)
  sha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip();meta={'sport':s,'market':'winner','model_version':ver,'feature_version':'strict-pit-v14-multiscale-form-robust-features','training_cutoff_utc':rows[sel-1][1],'git_commit_sha':sha,'artifact_path':str(path.relative_to(ROOT)),'quality_status':'ACCEPTED_LOCKED_HOLDOUT','selection_models':list(best),'ensemble_weights':candidate_weights,'ensemble_strategy':candidate_label,'selection_oos':oos,'ensemble_selection':scores,'weighted_pair_oos':wa_metric,'weighted_pair_win_rate':wa_win_rate,'weighted_pair_mean_delta':wa_mean_delta,'weighted_pair_fold_delta_std':wa_fold_std,'weighted_pair_robust_gain':wa_robust_gain,'weighted_pair_oos':wa_metric,'holdout_metrics':hold,'probability_calibration':{k:v for k,v in calibration.items() if k!='model'},'holdout_frozen':True,'production_fit_excludes_holdout':True,'dynamic_router':router_eval,'dynamic_router_holdout':router_holdout,'dynamic_router_status':'PRODUCTION_ROUTABLE_AFTER_GATES' if router_accept else 'FALLBACK_FIXED_ENSEMBLE'}
  c.execute('INSERT INTO model_state_snapshot(snapshot_id,sport,market,as_of_utc,model_version,feature_version,training_cutoff_utc,dataset_hash,git_commit_sha,artifact_path,quality_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(h(meta),s,'winner',utc(),ver,meta['feature_version'],rows[sel-1][1],h([(r[0],r[1],r[2]) for r in rows[:sel]]),sha,str(path.relative_to(ROOT)),'ACCEPTED_LOCKED_HOLDOUT',json.dumps(meta,ensure_ascii=False)));c.commit()
  out={'sport':s,'status':'TRAINED','models':list(best),'model_version':ver,'feature_version':meta['feature_version'],'training_rows':sel,'frozen_holdout_rows':hn,'features':len(fs),'training_cutoff_utc':meta['training_cutoff_utc'],'git_commit_sha':sha,'artifact_path':meta['artifact_path'],'selection_oos':oos,'ensemble_selection':scores,'holdout_metrics':hold,'probability_calibration':{k:v for k,v in calibration.items() if k!='model'},'holdout_frozen':True,'production_fit_excludes_holdout':True,'dynamic_router':router_eval,'dynamic_router_holdout':router_holdout,'dynamic_router_status':('RESEARCH_ONLY_HOLDOUT_PASS_PENDING_PROMOTION' if router_accept else 'FALLBACK_FIXED_ENSEMBLE')};return _write_result(s,out)
 finally:c.close()
def main():
 import argparse
 a=argparse.ArgumentParser();a.add_argument('--sport',choices=SPORTS);x=a.parse_args();print(json.dumps([train(s) for s in ([x.sport] if x.sport else SPORTS)],ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
