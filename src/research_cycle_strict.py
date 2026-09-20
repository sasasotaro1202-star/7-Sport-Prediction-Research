from __future__ import annotations
import hashlib,json,sqlite3,subprocess
from pathlib import Path
from itertools import combinations
import joblib,numpy as np
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
def _write_result(s, payload):
    """Persist every research outcome, including DEFERRED/REJECTED states."""
    RESULTS.mkdir(parents=True,exist_ok=True)
    (RESULTS/f'{s}.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    return payload

def _carry_forward_previous(c, sport, previous):
    """Keep the last accepted production model during a transient PIT/data outage.
    This never creates a new model: it only re-registers an already accepted,
    holdout-frozen artifact when the current run cannot reproduce enough strict
    PIT rows. The feature schema must still match the current production schema.
    """
    if not isinstance(previous, dict) or previous.get("status") != "TRAINED":
        return None
    if previous.get("feature_version") != "strict-pit-v13-bounded-ensemble-frozen-holdout":
        return None
    artifact = _restore_historical_artifact(sport, previous)
    if artifact is None:
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
   carried=_carry_forward_previous(c,s,previous)
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
  names=list(base.pool());start=max(60,int(sel*.65));step=max(10,min(30,int(sel*.06)));oos={}
  for name in names:
   p=[];t=[]
   for end in range(start,sel,step):
    te=min(end+step,sel)
    if len(np.unique(y[:end]))<2:continue
    m=base.pool()[name];m.fit(X[:end],y[:end]);p+=m.predict_proba(X[end:te])[:,1].tolist();t+=y[end:te].tolist()
   if len(t)>=30 and len(set(t))>1:oos[name]=base.metric(t,p)
  if not oos:return _write_result(s,{'sport':s,'status':'DEFERRED','reason':'no_valid_walk_forward_folds','rows':len(rows)})
  rank=sorted(oos,key=lambda k:(oos[k]['logloss'],oos[k]['brier'],oos[k]['ece']))
  # Evaluate every single model plus every pair among the three strongest singles.
  # This keeps ensemble search bounded while avoiding selection bias from considering only one arbitrary pair.
  cands=[(n,) for n in rank[:3]]+list(combinations(rank[:3],2))
  scores={}
  for spec in cands:
   p=[];t=[]
   for end in range(start,sel,step):
    te=min(end+step,sel)
    if len(np.unique(y[:end]))<2:continue
    ps=[]
    for name in spec:
     m=base.pool()[name];m.fit(X[:end],y[:end]);ps.append(m.predict_proba(X[end:te])[:,1])
    p+=np.mean(ps,axis=0).tolist();t+=y[end:te].tolist()
   if len(t)>=30 and len(set(t))>1:scores['+'.join(spec)]=base.metric(t,p)
  if not scores:return _write_result(s,{'sport':s,'status':'DEFERRED','reason':'no_valid_ensemble_selection_folds','rows':len(rows)})
  best_key=min(scores,key=lambda k:(scores[k]['logloss'],scores[k]['brier'],scores[k]['ece']));best=tuple(best_key.split('+'))
  models=[]
  for name in best:m=base.pool()[name];m.fit(X[:sel],y[:sel]);models.append(m)
  hp=np.mean([m.predict_proba(X[sel:])[:,1] for m in models],axis=0);hold=base.metric(y[sel:],hp);hold['models']=list(best)
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
  router_eval=router.evaluate_router(X,y,router_names,sel,start,step,base.pool,base.metric)
  router_accept = (router_eval.get('status') == 'EVALUATED'
                   and router_eval['logloss_improvement'] >= max(.001,.005*scores[best_key]['logloss'])
                   and router_eval['brier_improvement'] >= -.002
                   and router_eval['ece_change'] <= .02)
  ver=h({'sport':s,'features':fs,'models':best,'oos':oos,'ensemble_selection':scores,'holdout':hold,'router':router_eval,'router_accept':router_accept,'cutoff':rows[sel-1][1]});MODELS.mkdir(parents=True,exist_ok=True);RESULTS.mkdir(parents=True,exist_ok=True);path=MODELS/f'{s}_current.joblib';joblib.dump({'models':models,'model_names':list(best),'features':fs,'sport':s,'model_version':ver,'training_rows':sel,'frozen_holdout_rows':hn,'dynamic_router_status':'RESEARCH_ONLY_OOS_PASS_PENDING_HOLDOUT' if router_accept else 'FALLBACK_FIXED_ENSEMBLE','dynamic_router_eval':router_eval},path)
  sha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip();meta={'sport':s,'market':'winner','model_version':ver,'feature_version':'strict-pit-v13-bounded-ensemble-frozen-holdout','training_cutoff_utc':rows[sel-1][1],'git_commit_sha':sha,'artifact_path':str(path.relative_to(ROOT)),'quality_status':'ACCEPTED_LOCKED_HOLDOUT','selection_models':list(best),'selection_oos':oos,'ensemble_selection':scores,'holdout_metrics':hold,'holdout_frozen':True,'production_fit_excludes_holdout':True,'dynamic_router':router_eval,'dynamic_router_status':'CHALLENGER_ACCEPTED_OOS' if router_accept else 'FALLBACK_FIXED_ENSEMBLE'}
  c.execute('INSERT INTO model_state_snapshot(snapshot_id,sport,market,as_of_utc,model_version,feature_version,training_cutoff_utc,dataset_hash,git_commit_sha,artifact_path,quality_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(h(meta),s,'winner',utc(),ver,meta['feature_version'],rows[sel-1][1],h([(r[0],r[1],r[2]) for r in rows[:sel]]),sha,str(path.relative_to(ROOT)),'ACCEPTED_LOCKED_HOLDOUT',json.dumps(meta,ensure_ascii=False)));c.commit()
  out={'sport':s,'status':'TRAINED','models':list(best),'model_version':ver,'feature_version':meta['feature_version'],'training_rows':sel,'frozen_holdout_rows':hn,'features':len(fs),'training_cutoff_utc':meta['training_cutoff_utc'],'git_commit_sha':sha,'artifact_path':meta['artifact_path'],'selection_oos':oos,'ensemble_selection':scores,'holdout_metrics':hold,'holdout_frozen':True,'production_fit_excludes_holdout':True,'dynamic_router':router_eval,'dynamic_router_status':('RESEARCH_ONLY_OOS_PASS_PENDING_HOLDOUT' if router_accept else 'FALLBACK_FIXED_ENSEMBLE')};return _write_result(s,out)
 finally:c.close()
def main():
 import argparse
 a=argparse.ArgumentParser();a.add_argument('--sport',choices=SPORTS);x=a.parse_args();print(json.dumps([train(s) for s in ([x.sport] if x.sport else SPORTS)],ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
