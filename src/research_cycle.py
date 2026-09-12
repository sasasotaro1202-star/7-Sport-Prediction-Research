from __future__ import annotations
import hashlib, json, os, sqlite3, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
import joblib, numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'
MODELS=ROOT/'models/research'; RESULTS=ROOT/'results/research'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1')

# Each sport has its own market/feature vocabulary. Unknown stats are never silently mapped.
POLICY={
 'valorant':('rating','acs','adr','kast','k_d','fk_fd'),
 'basketball':('points','rebounds','assists','steals','blocks','turnovers','fieldGoalPct','threePointPct','freeThrowPct'),
 'volleyball':('attack','serve','receive','block','error','sideout'),
 'tennis':('ace','double_fault','first_serve','first_serve_points_won','break_points_saved','break_points_won'),
 'ufc':('sig_str','takedown','td_pct','sub_attempts','control_time'),
 'rizin':('sig_str','takedown','td_pct','sub_attempts','control_time'),
 'f1':('results.position','results.points','qualifying.position','pitstops.lap','pitstops.time')
}


def utc(): return datetime.now(timezone.utc).isoformat()
def h(x): return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()[:16]

def ece(y,p,bins=10):
    y=np.asarray(y); p=np.asarray(p); out=0.0
    for lo,hi in zip(np.linspace(0,1,bins,endpoint=False),np.linspace(0,1,bins)):
        m=(p>=lo)&(p<hi if hi<1 else p<=hi)
        if m.any(): out += m.mean()*abs(y[m].mean()-p[m].mean())
    return float(out)

def model_pool(seed=42):
    return {
      'logistic':Pipeline([('imp',SimpleImputer(strategy='median')),('scale',StandardScaler()),('model',LogisticRegression(max_iter=2000,C=1.0,random_state=seed))]),
      'extra_trees':Pipeline([('imp',SimpleImputer(strategy='median')),('model',ExtraTreesClassifier(n_estimators=400,min_samples_leaf=3,max_features='sqrt',random_state=seed,n_jobs=-1,class_weight='balanced'))]),
      'random_forest':Pipeline([('imp',SimpleImputer(strategy='median')),('model',RandomForestClassifier(n_estimators=400,min_samples_leaf=3,max_features='sqrt',random_state=seed,n_jobs=-1,class_weight='balanced'))]),
      'hist_gb':Pipeline([('imp',SimpleImputer(strategy='median')),('model',HistGradientBoostingClassifier(max_iter=300,learning_rate=.04,l2_regularization=.5,random_state=seed))])}

def stat_columns(c,sport):
    wanted=POLICY[sport]
    q=','.join('?' for _ in wanted)
    rows=c.execute(f"SELECT stat_name FROM match_stats WHERE sport=? AND stat_name IN ({q}) GROUP BY stat_name",(sport,*wanted)).fetchall()
    return [r[0] for r in rows]

def build_rows(c,sport):
    cols=stat_columns(c,sport)
    if not cols: return [],[]
    rows=[]
    events=c.execute("SELECT event_id,event_time_utc FROM event WHERE sport=? AND event_time_utc IS NOT NULL ORDER BY event_time_utc",(sport,)).fetchall()
    for eid,et in events:
        o=c.execute("SELECT outcome FROM event_outcome WHERE event_id=? AND outcome_status='VERIFIED'",(eid,)).fetchone()
        if not o or o[0] not in ('A','B'): continue
        ps=c.execute("SELECT participant_id,side FROM event_participant WHERE event_id=? AND side IN ('A','B')",(eid,)).fetchall()
        if len(ps)<2: continue
        cutoff=et
        feat={}
        for pid,side in ps:
            for stat in cols:
                vals=c.execute("""SELECT ms.value_num FROM match_stats ms JOIN event pe ON pe.event_id=ms.event_id
                                  WHERE ms.sport=? AND ms.participant_id=? AND ms.stat_name=? AND pe.event_time_utc IS NOT NULL
                                  AND pe.event_time_utc < ? AND ms.value_num IS NOT NULL ORDER BY pe.event_time_utc DESC LIMIT 20""",(sport,pid,stat,cutoff)).fetchall()
                x=np.array([v[0] for v in vals],dtype=float)
                feat[f'{side}__{stat}__n']=float(len(x))
                feat[f'{side}__{stat}__mean']=float(x.mean()) if len(x) else np.nan
                feat[f'{side}__{stat}__last']=float(x[0]) if len(x) else np.nan
                feat[f'{side}__{stat}__std']=float(x.std()) if len(x)>1 else np.nan
                feat[f'{side}__{stat}__trend']=float(x[0]-x[-1]) if len(x)>1 else np.nan
        # Difference features are the actual matchup representation.
        for stat in cols:
            for suffix in ('mean','last','std','trend','n'):
                a=feat.get(f'A__{stat}__{suffix}',np.nan); b=feat.get(f'B__{stat}__{suffix}',np.nan)
                feat[f'D__{stat}__{suffix}']=a-b if np.isfinite(a) and np.isfinite(b) else np.nan
        rows.append((eid,et,0 if o[0]=='A' else 1,feat))
    return rows,sorted({k for _,_,_,f in rows for k in f})

def train_sport(sport):
    c=sqlite3.connect(DB); rows,features=build_rows(c,sport)
    if len(rows)<60 or len(features)<2:
        result={'sport':sport,'status':'DEFERRED','reason':'insufficient_verified_PIT_training_rows','rows':len(rows),'features':len(features),'timestamp_utc':utc()}
        c.close(); return result
    X=np.array([[r[3].get(f,np.nan) for f in features] for r in rows],dtype=float); y=np.array([r[2] for r in rows],dtype=int)
    split=max(40,int(len(rows)*0.70)); results=[]; best=None
    for name,proto in model_pool().items():
        probs=[]; truth=[]; preds=[]; folds=[]
        # Expanding-window, strictly chronological OOS. Never random-split.
        for end in range(split,len(rows),max(10,min(50,len(rows)-split))):
            test_end=min(end+20,len(rows));
            if test_end<=end: break
            model=proto
            model.fit(X[:end],y[:end]); p=model.predict_proba(X[end:test_end])[:,1]; z=(p>=.5).astype(int)
            probs.extend(p.tolist()); truth.extend(y[end:test_end].tolist()); preds.extend(z.tolist()); folds.append({'train_end':rows[end-1][1],'test_start':rows[end][1],'test_end':rows[test_end-1][1],'n':test_end-end})
        if len(set(truth))<2: continue
        ll=log_loss(truth,np.column_stack([1-np.array(probs),np.array(probs)]),labels=[0,1]); br=brier_score_loss(truth,probs); acc=accuracy_score(truth,preds); ec=ece(np.array(truth),np.array(probs))
        results.append({'model':name,'logloss':ll,'brier':br,'accuracy':acc,'ece':ec,'oos_n':len(truth),'folds':folds})
        score=ll+0.25*br+0.25*ec
        if best is None or score<best[0]: best=(score,name)
    if not results:
        c.close(); return {'sport':sport,'status':'DEFERRED','reason':'no_valid_oos_folds','rows':len(rows)}
    best_name=best[1]; final=model_pool()[best_name]; final.fit(X,y)
    version=h({'sport':sport,'features':features,'model':best_name,'rows':len(rows),'last_event':rows[-1][1]})
    MODELS.mkdir(parents=True,exist_ok=True); RESULTS.mkdir(parents=True,exist_ok=True)
    artifact=MODELS/f'{sport}_{version}.joblib'; joblib.dump({'model':final,'features':features,'sport':sport,'model_version':version,'training_rows':len(rows)},artifact)
    gitsha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip() or None
    metadata={'sport':sport,'market':'winner','model_version':version,'feature_version':'pit-v1','training_cutoff_utc':rows[-1][1],'git_commit_sha':gitsha,'artifact_path':str(artifact.relative_to(ROOT)),'quality_status':'ACCEPTED_AFTER_OOS','metrics':results}
    c.execute('''INSERT INTO model_state_snapshot(snapshot_id,sport,market,as_of_utc,model_version,feature_version,training_cutoff_utc,dataset_hash,git_commit_sha,artifact_path,quality_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(h(metadata),sport,'winner',utc(),version,'pit-v1',rows[-1][1],h([(r[0],r[1],r[2]) for r in rows]),gitsha,str(artifact.relative_to(ROOT)),'ACCEPTED_AFTER_OOS',json.dumps(metadata,ensure_ascii=False)))
    c.commit(); c.close();
    out={'sport':sport,'status':'TRAINED','model':best_name,'model_version':version,'training_rows':len(rows),'features':len(features),'metrics':results}
    (RESULTS/f'{sport}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); return out

def main():
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--sport',choices=SPORTS); a=ap.parse_args(); sports=[a.sport] if a.sport else SPORTS
    out=[train_sport(s) for s in sports]; print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
