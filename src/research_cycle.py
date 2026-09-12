from __future__ import annotations
import hashlib, json, subprocess, sqlite3
from datetime import datetime, timezone
from pathlib import Path
import joblib, numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'; MODELS=ROOT/'models/research'; RESULTS=ROOT/'results/research'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1')
POLICY={'valorant':('rating','acs','adr','kast','k_d','fk_fd'),'basketball':('points','rebounds','assists','steals','blocks','turnovers','fieldGoalPct','threePointPct','freeThrowPct'),'volleyball':('attack','serve','receive','block','error','sideout'),'tennis':('ace','double_fault','first_serve','first_serve_points_won','break_points_saved','break_points_won'),'ufc':('sig_str','takedown','td_pct','sub_attempts','control_time'),'rizin':('sig_str','takedown','td_pct','sub_attempts','control_time'),'f1':('results.position','results.points','qualifying.position','pitstops.lap','pitstops.time')}
def utc(): return datetime.now(timezone.utc).isoformat()
def h(x): return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()[:16]
def ece(y,p,bins=10):
    y=np.asarray(y); p=np.asarray(p); out=0.0
    for lo,hi in zip(np.linspace(0,1,bins,endpoint=False),np.linspace(0,1,bins)):
        m=(p>=lo)&(p<hi if hi<1 else p<=hi)
        if m.any(): out += m.mean()*abs(y[m].mean()-p[m].mean())
    return float(out)
def model_pool(seed=42):
    base={'logistic':Pipeline([('imp',SimpleImputer(strategy='median')),('scale',StandardScaler()),('model',LogisticRegression(max_iter=3000,C=1.0,random_state=seed))]),'extra_trees':Pipeline([('imp',SimpleImputer(strategy='median')),('model',ExtraTreesClassifier(n_estimators=500,min_samples_leaf=3,max_features='sqrt',random_state=seed,n_jobs=-1,class_weight='balanced'))]),'random_forest':Pipeline([('imp',SimpleImputer(strategy='median')),('model',RandomForestClassifier(n_estimators=500,min_samples_leaf=3,max_features='sqrt',random_state=seed,n_jobs=-1,class_weight='balanced'))]),'hist_gb':Pipeline([('imp',SimpleImputer(strategy='median')),('model',HistGradientBoostingClassifier(max_iter=350,learning_rate=.035,l2_regularization=.75,random_state=seed))])}
    return {k:CalibratedClassifierCV(v,method='sigmoid',cv=3,n_jobs=-1) for k,v in base.items()}
def stat_columns(c,sport):
    wanted=POLICY[sport]; q=','.join('?' for _ in wanted)
    return [r[0] for r in c.execute(f"SELECT stat_name FROM match_stats WHERE sport=? AND stat_name IN ({q}) GROUP BY stat_name",(sport,*wanted)).fetchall()]
def build_rows(c,sport):
    cols=stat_columns(c,sport)
    if not cols: return [],[]
    rows=[]
    events=c.execute("SELECT event_id,event_time_utc FROM event WHERE sport=? AND event_time_utc IS NOT NULL ORDER BY event_time_utc,event_id",(sport,)).fetchall()
    for eid,et in events:
        o=c.execute("SELECT outcome FROM event_outcome WHERE event_id=? AND outcome_status='VERIFIED'",(eid,)).fetchone()
        if not o or o[0] not in ('A','B'): continue
        ps=c.execute("SELECT participant_id,side FROM event_participant WHERE event_id=? AND side IN ('A','B') AND participant_id IS NOT NULL GROUP BY participant_id,side ORDER BY side",(eid,)).fetchall()
        if len(ps)!=2: continue
        cutoff=f"{et}"
        # Default replay cutoff is event time minus 60 minutes. Features and source availability
        # must both be known by that cutoff; event time itself is never a sufficient proxy.
        feat={}
        for pid,side in ps:
            for stat in cols:
                vals=c.execute("""SELECT ms.value_num FROM match_stats ms JOIN event pe ON pe.event_id=ms.event_id
                                  JOIN source_snapshot ss ON ss.source_url=ms.source_url AND ss.source=ms.source
                                  WHERE ms.sport=? AND ms.participant_id=? AND ms.stat_name=?
                                  AND pe.event_time_utc IS NOT NULL AND pe.event_time_utc < ?
                                  AND ms.value_num IS NOT NULL AND ms.effective_at_utc IS NOT NULL
                                  AND ms.effective_at_utc <= datetime(?, '-60 minutes')
                                  AND ss.availability_status='EXACT' AND ss.source_available_at_utc IS NOT NULL
                                  AND ss.source_available_at_utc <= datetime(?, '-60 minutes')
                                  ORDER BY pe.event_time_utc DESC,ms.stat_id DESC LIMIT 20""",(sport,pid,stat,et,et,et)).fetchall()
                x=np.asarray([v[0] for v in vals],dtype=float)
                feat[f'{side}__{stat}__n']=float(len(x)); feat[f'{side}__{stat}__mean']=float(x.mean()) if len(x) else np.nan; feat[f'{side}__{stat}__last']=float(x[0]) if len(x) else np.nan; feat[f'{side}__{stat}__std']=float(x.std()) if len(x)>1 else np.nan; feat[f'{side}__{stat}__trend']=float(x[0]-x[-1]) if len(x)>1 else np.nan
        for stat in cols:
            for suffix in ('mean','last','std','trend','n'):
                a=feat.get(f'A__{stat}__{suffix}',np.nan); b=feat.get(f'B__{stat}__{suffix}',np.nan); feat[f'D__{stat}__{suffix}']=a-b if np.isfinite(a) and np.isfinite(b) else np.nan
        av=sum(np.isfinite(v) for k,v in feat.items() if k.startswith('A__')); bv=sum(np.isfinite(v) for k,v in feat.items() if k.startswith('B__'))
        if av==0 or bv==0: continue
        rows.append((eid,et,0 if o[0]=='A' else 1,feat))
    return rows,sorted({k for _,_,_,f in rows for k in f})
def incumbent(c,sport):
    r=c.execute("SELECT model_version,metadata_json,artifact_path FROM model_state_snapshot WHERE sport=? AND market='winner' ORDER BY as_of_utc DESC LIMIT 1",(sport,)).fetchone()
    if not r: return None
    try: return {'version':r[0],'metadata':json.loads(r[1]),'artifact':r[2]}
    except Exception: return None
def train_sport(sport):
    c=sqlite3.connect(DB); rows,features=build_rows(c,sport)
    if len(rows)<80 or len(features)<2:
        out={'sport':sport,'status':'DEFERRED','reason':'insufficient_strict_PIT_training_rows','rows':len(rows),'features':len(features),'timestamp_utc':utc()}; c.close(); return out
    X=np.array([[r[3].get(f,np.nan) for f in features] for r in rows],dtype=float); y=np.array([r[2] for r in rows],dtype=int); split=max(50,int(len(rows)*.70)); pool=model_pool(); results=[]; step=max(10,min(30,len(rows)-split))
    for name,proto in pool.items():
        probs=[]; truth=[]; preds=[]; folds=[]
        for end in range(split,len(rows),step):
            test_end=min(end+step,len(rows))
            if test_end<=end or len(np.unique(y[:end]))<2: continue
            model=proto; model.fit(X[:end],y[:end]); p=model.predict_proba(X[end:test_end])[:,1]; z=(p>=.5).astype(int); probs.extend(p.tolist()); truth.extend(y[end:test_end].tolist()); preds.extend(z.tolist()); folds.append({'train_end':rows[end-1][1],'test_start':rows[end][1],'test_end':rows[test_end-1][1],'n':test_end-end})
        if len(truth)<20 or len(set(truth))<2: continue
        ll=log_loss(truth,np.column_stack([1-np.asarray(probs),np.asarray(probs)]),labels=[0,1]); br=brier_score_loss(truth,probs); acc=accuracy_score(truth,preds); ec=ece(np.asarray(truth),np.asarray(probs)); results.append({'model':name,'logloss':float(ll),'brier':float(br),'accuracy':float(acc),'ece':float(ec),'oos_n':len(truth),'folds':folds})
    if not results:
        c.close(); return {'sport':sport,'status':'DEFERRED','reason':'no_valid_oos_folds','rows':len(rows)}
    results.sort(key=lambda z:(z['logloss'],z['brier'],z['ece'])); best=results[0]; inc=incumbent(c,sport); accept=True; gate_reason='initial_model'
    if inc:
        old=inc['metadata'].get('metrics',[]); oldbest=min(old,key=lambda z:z.get('logloss',1e9)) if old else None
        if oldbest:
            oldll=float(oldbest.get('logloss',1e9)); newll=float(best['logloss']); tol=max(.002,0.01*oldll); accept=newll <= oldll-tol; gate_reason=f"challenger_logloss={newll:.6f}; incumbent_logloss={oldll:.6f}; required_improvement={tol:.6f}"
        else: gate_reason='incumbent_missing_metrics'
    if not accept:
        out={'sport':sport,'status':'REJECTED_CHALLENGER','reason':gate_reason,'candidate':best,'all_models':results,'training_rows':len(rows)}; c.close(); RESULTS.mkdir(parents=True,exist_ok=True); (RESULTS/f'{sport}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); return out
    final=pool[best['model']]; final.fit(X,y); version=h({'sport':sport,'features':features,'model':best['model'],'rows':len(rows),'last_event':rows[-1][1],'metrics':best}); MODELS.mkdir(parents=True,exist_ok=True); RESULTS.mkdir(parents=True,exist_ok=True); artifact=MODELS/f'{sport}_{version}.joblib'; joblib.dump({'model':final,'features':features,'sport':sport,'model_version':version,'training_rows':len(rows)},artifact); gitsha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip() or None
    metadata={'sport':sport,'market':'winner','model_version':version,'feature_version':'strict-pit-v4-source-exact-60m','training_cutoff_utc':rows[-1][1],'git_commit_sha':gitsha,'artifact_path':str(artifact.relative_to(ROOT)),'quality_status':'ACCEPTED_AFTER_OOS','selection_gate':gate_reason,'metrics':results}
    c.execute('''INSERT INTO model_state_snapshot(snapshot_id,sport,market,as_of_utc,model_version,feature_version,training_cutoff_utc,dataset_hash,git_commit_sha,artifact_path,quality_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(h(metadata),sport,'winner',utc(),version,'strict-pit-v4-source-exact-60m',rows[-1][1],h([(r[0],r[1],r[2]) for r in rows]),gitsha,str(artifact.relative_to(ROOT)),'ACCEPTED_AFTER_OOS',json.dumps(metadata,ensure_ascii=False))); c.commit(); c.close()
    out={'sport':sport,'status':'TRAINED','model':best['model'],'model_version':version,'training_rows':len(rows),'features':len(features),'metrics':results,'selection_gate':gate_reason}; (RESULTS/f'{sport}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); return out
def main():
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--sport',choices=SPORTS); a=ap.parse_args(); sports=[a.sport] if a.sport else SPORTS; print(json.dumps([train_sport(s) for s in sports],ensure_ascii=False,indent=2))
if __name__=='__main__': main()
