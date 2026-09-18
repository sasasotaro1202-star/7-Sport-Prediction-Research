from __future__ import annotations
import hashlib,json,sqlite3,subprocess
from pathlib import Path
from itertools import combinations
import joblib,numpy as np
from src import research_cycle_v4 as base
ROOT=Path(__file__).resolve().parents[1];DB=ROOT/'data/db/sports_v45.sqlite';MODELS=ROOT/'models/research';RESULTS=ROOT/'results/research'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1','rugby')
def utc():
 from datetime import datetime,timezone
 return datetime.now(timezone.utc).isoformat()
def h(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()[:16]
def f1():
 c=sqlite3.connect(DB)
 try:n=c.execute("select count(*) from event where sport='f1'").fetchone()[0];e=c.execute("select count(*) from source_snapshot where source='OpenF1' and availability_status='EXACT'").fetchone()[0]
 finally:c.close()
 return {'sport':'f1','status':'DEFERRED_PIT','events':int(n),'exact_pit_source_snapshots':int(e),'reason':'OpenF1 historical availability is not proven before the 60-minute cutoff; no leakage-prone proxy is permitted'}
def train(s):
 if s=='f1':
  o=f1();RESULTS.mkdir(parents=True,exist_ok=True);(RESULTS/'f1.json').write_text(json.dumps(o,ensure_ascii=False,indent=2));return o
 c=sqlite3.connect(DB)
 try:
  rows,fs=base.build(c,s)
  if len(rows)<120:return {'sport':s,'status':'DEFERRED','reason':'insufficient_strict_PIT_rows','rows':len(rows),'features':len(fs)}
  X=np.array([[r[3].get(f,np.nan) for f in fs] for r in rows]);y=np.array([r[2] for r in rows]);sel=int(len(rows)*.78);hn=len(rows)-sel
  if hn<30 or len(np.unique(y[sel:]))<2:return {'sport':s,'status':'DEFERRED','reason':'insufficient_frozen_holdout','rows':len(rows),'holdout_rows':hn}
  names=list(base.pool());start=max(60,int(sel*.65));step=max(10,min(30,int(sel*.06)));oos={}
  for name in names:
   p=[];t=[]
   for end in range(start,sel,step):
    te=min(end+step,sel)
    if len(np.unique(y[:end]))<2:continue
    m=base.pool()[name];m.fit(X[:end],y[:end]);p+=m.predict_proba(X[end:te])[:,1].tolist();t+=y[end:te].tolist()
   if len(t)>=30 and len(set(t))>1:oos[name]=base.metric(t,p)
  if not oos:return {'sport':s,'status':'DEFERRED','reason':'no_valid_walk_forward_folds','rows':len(rows)}
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
  if not scores:return {'sport':s,'status':'DEFERRED','reason':'no_valid_ensemble_selection_folds','rows':len(rows)}
  best_key=min(scores,key=lambda k:(scores[k]['logloss'],scores[k]['brier'],scores[k]['ece']));best=tuple(best_key.split('+'))
  models=[]
  for name in best:m=base.pool()[name];m.fit(X[:sel],y[:sel]);models.append(m)
  hp=np.mean([m.predict_proba(X[sel:])[:,1] for m in models],axis=0);hold=base.metric(y[sel:],hp);hold['models']=list(best)
  if hold['ece']>.20:return {'sport':s,'status':'REJECTED_HOLDOUT_CALIBRATION','holdout_metrics':hold,'selection_oos':oos,'ensemble_selection':scores}
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
    return {'sport':s,'status':'REJECTED_CHALLENGER','reason':f"new_ll={hold['logloss']:.6f};old_ll={old_ll:.6f};improvement={ll_improvement:.6f};required={tol:.6f};brier_guard={brier_guard};ece_guard={ece_guard}",'holdout_metrics':hold,'selection_oos':oos,'ensemble_selection':scores}
  ver=h({'sport':s,'features':fs,'models':best,'oos':oos,'ensemble_selection':scores,'holdout':hold,'cutoff':rows[sel-1][1]});MODELS.mkdir(parents=True,exist_ok=True);RESULTS.mkdir(parents=True,exist_ok=True);path=MODELS/f'{s}_current.joblib';joblib.dump({'models':models,'model_names':list(best),'features':fs,'sport':s,'model_version':ver,'training_rows':sel,'frozen_holdout_rows':hn},path)
  sha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip();meta={'sport':s,'market':'winner','model_version':ver,'feature_version':'strict-pit-v13-bounded-ensemble-frozen-holdout','training_cutoff_utc':rows[sel-1][1],'git_commit_sha':sha,'artifact_path':str(path.relative_to(ROOT)),'quality_status':'ACCEPTED_LOCKED_HOLDOUT','selection_models':list(best),'selection_oos':oos,'ensemble_selection':scores,'holdout_metrics':hold,'holdout_frozen':True,'production_fit_excludes_holdout':True}
  c.execute('INSERT INTO model_state_snapshot(snapshot_id,sport,market,as_of_utc,model_version,feature_version,training_cutoff_utc,dataset_hash,git_commit_sha,artifact_path,quality_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(h(meta),s,'winner',utc(),ver,meta['feature_version'],rows[sel-1][1],h([(r[0],r[1],r[2]) for r in rows[:sel]]),sha,str(path.relative_to(ROOT)),'ACCEPTED_LOCKED_HOLDOUT',json.dumps(meta,ensure_ascii=False)));c.commit()
  out={'sport':s,'status':'TRAINED','models':list(best),'model_version':ver,'training_rows':sel,'frozen_holdout_rows':hn,'features':len(fs),'selection_oos':oos,'ensemble_selection':scores,'holdout_metrics':hold,'production_fit_excludes_holdout':True};(RESULTS/f'{s}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));return out
 finally:c.close()
def main():
 import argparse
 a=argparse.ArgumentParser();a.add_argument('--sport',choices=SPORTS);x=a.parse_args();print(json.dumps([train(s) for s in ([x.sport] if x.sport else SPORTS)],ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
