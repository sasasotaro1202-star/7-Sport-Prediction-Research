from __future__ import annotations
import sys, json, sqlite3, hashlib, subprocess
from pathlib import Path
import joblib, numpy as np
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
import src.research_cycle as rc

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'; MODELS=ROOT/'models/research'; RESULTS=ROOT/'results/research'
def _hash(x): return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()[:16]
def _locked_train_eval(proto,X,y,train_end,test_end,step):
    probs=[]; truth=[]; preds=[]; folds=[]
    for end in range(train_end,test_end,step):
        te=min(end+step,test_end)
        if te<=end or len(np.unique(y[:end]))<2: continue
        m=proto; m.fit(X[:end],y[:end]); p=m.predict_proba(X[end:te])[:,1]
        probs.extend(p.tolist()); truth.extend(y[end:te].tolist()); preds.extend((p>=.5).astype(int).tolist())
        folds.append({'train_end_index':end,'test_start_index':end,'test_end_index':te,'n':te-end})
    if len(truth)<20 or len(set(truth))<2:return None
    a=np.asarray(truth); p=np.asarray(probs)
    return {'logloss':float(log_loss(a,np.column_stack([1-p,p]),labels=[0,1])),'brier':float(brier_score_loss(a,p)),'accuracy':float(accuracy_score(a,preds)),'ece':float(rc.ece(a,p)),'oos_n':len(a),'folds':folds}
def train_sport_locked(sport):
    c=sqlite3.connect(DB); rows,features=rc.build_rows(c,sport); n=len(rows)
    if n<140 or len(features)<2:
        c.close(); return {'sport':sport,'status':'DEFERRED','reason':'insufficient_strict_PIT_rows_for_locked_protocol','rows':n,'features':len(features)}
    X=np.array([[r[3].get(f,np.nan) for f in features] for r in rows],dtype=float); y=np.array([r[2] for r in rows],dtype=int)
    dev_start=max(60,int(n*.55)); selection_end=max(dev_start+40,int(n*.78)); holdout_start=selection_end
    if n-holdout_start<30:
        c.close(); return {'sport':sport,'status':'DEFERRED','reason':'locked_holdout_too_small','rows':n}
    step=max(10,min(25,selection_end-dev_start)); dev=[]
    for name,proto in rc.model_pool().items():
        m=_locked_train_eval(proto,X,y,dev_start,selection_end,step)
        if m: m['model']=name; dev.append(m)
    if not dev:
        c.close(); return {'sport':sport,'status':'DEFERRED','reason':'no_valid_development_oos','rows':n}
    dev.sort(key=lambda z:(z['logloss'],z['brier'],z['ece'])); selected=dev[0]['model']
    hold_model=rc.model_pool()[selected]; hold_model.fit(X[:holdout_start],y[:holdout_start]); hp=hold_model.predict_proba(X[holdout_start:])[:,1]; hy=y[holdout_start:]
    hold={'logloss':float(log_loss(hy,np.column_stack([1-hp,hp]),labels=[0,1])),'brier':float(brier_score_loss(hy,hp)),'accuracy':float(accuracy_score(hy,(hp>=.5).astype(int))),'ece':float(rc.ece(hy,hp)),'oos_n':len(hy)}
    inc=rc.incumbent(c,sport); accept=hold['ece']<=0.20; gate=f'locked_holdout_ece={hold["ece"]:.6f}'
    if inc and inc['metadata'].get('holdout_metrics'):
        old=inc['metadata']['holdout_metrics']; tol=max(.002,.01*float(old.get('logloss',1e9))); accept=accept and hold['logloss']<=float(old['logloss'])-tol
        gate += f'; challenger_logloss={hold["logloss"]:.6f}; incumbent_logloss={float(old["logloss"]):.6f}; required_improvement={tol:.6f}'
    if not accept:
        out={'sport':sport,'status':'REJECTED_CHALLENGER','reason':gate,'selected_model':selected,'development_models':dev,'holdout_metrics':hold,'training_rows':n}
        c.close(); RESULTS.mkdir(parents=True,exist_ok=True); (RESULTS/f'{sport}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); return out
    final=rc.model_pool()[selected]; final.fit(X,y); version=_hash({'sport':sport,'features':features,'model':selected,'rows':n,'last_event':rows[-1][1],'development':dev,'holdout':hold})
    MODELS.mkdir(parents=True,exist_ok=True); RESULTS.mkdir(parents=True,exist_ok=True); artifact=MODELS/f'{sport}_{version}.joblib'; joblib.dump({'model':final,'features':features,'sport':sport,'model_version':version,'training_rows':n},artifact)
    gitsha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip() or None
    metadata={'sport':sport,'market':'winner','model_version':version,'feature_version':'strict-pit-v5-locked-holdout','training_cutoff_utc':rows[-1][1],'git_commit_sha':gitsha,'artifact_path':str(artifact.relative_to(ROOT)),'quality_status':'ACCEPTED_AFTER_LOCKED_HOLDOUT','selection_gate':gate,'development_metrics':dev,'holdout_metrics':hold}
    c.execute("INSERT INTO model_state_snapshot(snapshot_id,sport,market,as_of_utc,model_version,feature_version,training_cutoff_utc,dataset_hash,git_commit_sha,artifact_path,quality_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(_hash(metadata),sport,'winner',rc.utc(),version,'strict-pit-v5-locked-holdout',rows[-1][1],_hash([(r[0],r[1],r[2]) for r in rows]),gitsha,str(artifact.relative_to(ROOT)),'ACCEPTED_AFTER_LOCKED_HOLDOUT',json.dumps(metadata,ensure_ascii=False)))
    c.commit(); c.close()
    out={'sport':sport,'status':'TRAINED','model':selected,'model_version':version,'training_rows':n,'features':len(features),'development_models':dev,'holdout_metrics':hold,'selection_gate':gate}; (RESULTS/f'{sport}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); return out
def main():
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--sport',choices=rc.SPORTS); a=ap.parse_args(); sports=[a.sport] if a.sport else list(rc.SPORTS); print(json.dumps([train_sport_locked(s) for s in sports],ensure_ascii=False,indent=2))
if __name__=='__main__': main()
