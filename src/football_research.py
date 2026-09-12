from __future__ import annotations
import hashlib, json, sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import joblib, numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV

ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'data/db/sports_v45.sqlite'; MODELS=ROOT/'models/research'; RESULTS=ROOT/'results/research'
STAT_NAMES=('home_goals','away_goals','home_shots','away_shots','home_sot','away_sot','home_corners','away_corners','home_fouls','away_fouls','home_yellow','away_yellow','home_red','away_red','home_odds_b365','draw_odds_b365','away_odds_b365','home_odds_avg','draw_odds_avg','away_odds_avg')

def utc(): return datetime.now(timezone.utc).isoformat()
def h(x): return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()[:16]

def pool(seed=42):
    base={
      'logistic':Pipeline([('imp',SimpleImputer(strategy='median')),('scale',StandardScaler()),('model',LogisticRegression(max_iter=4000,C=.5,random_state=seed))]),
      'extra_trees':Pipeline([('imp',SimpleImputer(strategy='median')),('model',ExtraTreesClassifier(n_estimators=700,min_samples_leaf=3,max_features='sqrt',random_state=seed,n_jobs=-1,class_weight='balanced'))]),
      'random_forest':Pipeline([('imp',SimpleImputer(strategy='median')),('model',RandomForestClassifier(n_estimators=700,min_samples_leaf=3,max_features='sqrt',random_state=seed,n_jobs=-1,class_weight='balanced'))]),
      'hist_gb':Pipeline([('imp',SimpleImputer(strategy='median')),('model',HistGradientBoostingClassifier(max_iter=400,learning_rate=.035,l2_regularization=1.0,random_state=seed))])}
    return {k:CalibratedClassifierCV(v,method='sigmoid',cv=3,n_jobs=-1) for k,v in base.items()}

def prior_stats(c,team_id,cutoff,n=8):
    out={}
    if not team_id:return out
    for stat in STAT_NAMES:
        rows=c.execute('''SELECT ms.value_num FROM match_stats ms JOIN event e ON e.event_id=ms.event_id WHERE ms.sport='football' AND ms.team_id=? AND ms.stat_name=? AND e.event_time_utc IS NOT NULL AND e.event_time_utc < ? AND ms.value_num IS NOT NULL AND ms.effective_at_utc IS NOT NULL AND ms.effective_at_utc <= ? ORDER BY e.event_time_utc DESC,ms.stat_id DESC LIMIT ?''',(team_id,stat,cutoff,cutoff,n)).fetchall()
        x=np.asarray([v[0] for v in rows],dtype=float)
        out[f'{stat}_mean']=float(x.mean()) if len(x) else np.nan; out[f'{stat}_last']=float(x[0]) if len(x) else np.nan; out[f'{stat}_std']=float(x.std()) if len(x)>1 else np.nan; out[f'{stat}_trend']=float(x[0]-x[-1]) if len(x)>1 else np.nan; out[f'{stat}_n']=float(len(x))
    return out

def features(c,home,away,cutoff):
    hf=prior_stats(c,home,cutoff); af=prior_stats(c,away,cutoff); f={}
    for k,v in hf.items():f['H__'+k]=v
    for k,v in af.items():f['A__'+k]=v
    for stat in STAT_NAMES:
        for suf in ('mean','last','std','trend','n'):
            a=f.get(f'H__{stat}_{suf}',np.nan); b=f.get(f'A__{stat}_{suf}',np.nan); f[f'D__{stat}_{suf}']=a-b if np.isfinite(a) and np.isfinite(b) else np.nan
    return f

def completed(c):
    q='''SELECT e.event_id,e.event_time_utc,e.competition_id,o.outcome,o.score_a,o.score_b,ep.side,ep.team_id FROM event e JOIN event_outcome o ON o.event_id=e.event_id AND o.outcome_status='VERIFIED' JOIN event_participant ep ON ep.event_id=e.event_id AND ep.side IN ('A','B') WHERE e.sport='football' AND e.event_time_utc IS NOT NULL ORDER BY e.event_time_utc,e.event_id'''
    d={}
    for eid,et,comp,out,sa,sb,side,tid in c.execute(q):
        d.setdefault(eid,{'event_id':eid,'time':et,'competition':comp,'outcome':out,'score_a':sa,'score_b':sb,'teams':{}})['teams'][side]=tid
    return [v for v in d.values() if set(v['teams'])=={'A','B'} and v['outcome'] in ('A','D','B')]

def train():
    c=sqlite3.connect(DB); rows=[]; featset=set(); labels={'A':0,'D':1,'B':2}
    for e in completed(c):
        f=features(c,e['teams']['A'],e['teams']['B'],e['time'])
        if sum(np.isfinite(v) for v in f.values())<10:continue
        rows.append((e['event_id'],e['time'],labels[e['outcome']],f)); featset.update(f)
    feats=sorted(featset)
    if len(rows)<120:
        out={'sport':'football','status':'DEFERRED','reason':'insufficient_training_rows','rows':len(rows),'features':len(feats),'timestamp_utc':utc()}; c.close(); return out
    X=np.asarray([[r[3].get(f,np.nan) for f in feats] for r in rows],dtype=float); y=np.asarray([r[2] for r in rows],dtype=int); split=max(80,int(len(rows)*.70)); results=[]
    for name,model in pool().items():
        probs=[]; truth=[]; preds=[]
        for end in range(split,len(rows),25):
            te=min(end+25,len(rows))
            if te<=end or len(np.unique(y[:end]))<3:continue
            model.fit(X[:end],y[:end]); p=model.predict_proba(X[end:te]); probs.extend(p.tolist()); truth.extend(y[end:te]); preds.extend(np.argmax(p,axis=1).tolist())
        if len(truth)<30 or len(set(truth))<3:continue
        results.append({'model':name,'logloss':float(log_loss(truth,np.asarray(probs),labels=[0,1,2])),'accuracy':float(accuracy_score(truth,preds)),'oos_n':len(truth)})
    if not results:
        c.close(); return {'sport':'football','status':'DEFERRED','reason':'no_valid_oos','rows':len(rows)}
    results.sort(key=lambda z:(z['logloss'],-z['accuracy'])); best=results[0]; gate='initial_model'; accept=True
    inc=c.execute("SELECT metadata_json FROM model_state_snapshot WHERE sport='football' AND market='winner_1x2' ORDER BY as_of_utc DESC LIMIT 1").fetchone()
    if inc:
        try:
            old=min(json.loads(inc[0]).get('metrics',[]),key=lambda z:z.get('logloss',1e9)); oldll=float(old['logloss']); newll=float(best['logloss']); req=max(.003,.01*oldll); accept=newll<=oldll-req; gate=f'challenger_logloss={newll:.6f}; incumbent_logloss={oldll:.6f}; required_improvement={req:.6f}'
        except Exception: gate='incumbent_metrics_unreadable'
    if not accept:
        out={'sport':'football','status':'REJECTED_CHALLENGER','reason':gate,'candidate':best,'all_models':results,'training_rows':len(rows)}; c.close(); RESULTS.mkdir(parents=True,exist_ok=True); (RESULTS/'football.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); return out
    final=pool()[best['model']]; final.fit(X,y); version=h({'sport':'football','features':feats,'model':best['model'],'rows':len(rows),'last_event':rows[-1][1],'metrics':best}); MODELS.mkdir(parents=True,exist_ok=True); RESULTS.mkdir(parents=True,exist_ok=True); artifact=MODELS/f'football_{version}.joblib'; joblib.dump({'model':final,'features':feats,'labels':labels,'model_version':version,'training_rows':len(rows)},artifact)
    meta={'sport':'football','market':'winner_1x2','model_version':version,'feature_version':'football-pit-v1','training_cutoff_utc':rows[-1][1],'artifact_path':str(artifact.relative_to(ROOT)),'quality_status':'ACCEPTED_AFTER_OOS','selection_gate':gate,'metrics':results}
    c.execute("INSERT INTO model_state_snapshot(snapshot_id,sport,market,as_of_utc,model_version,feature_version,training_cutoff_utc,dataset_hash,git_commit_sha,artifact_path,quality_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(h(meta),'football','winner_1x2',utc(),version,'football-pit-v1',rows[-1][1],h([(r[0],r[1],r[2]) for r in rows]),None,str(artifact.relative_to(ROOT)),'ACCEPTED_AFTER_OOS',json.dumps(meta,ensure_ascii=False))); c.commit()
    now=datetime.now(timezone.utc); end=(now+timedelta(days=7)).isoformat(); future=c.execute("""SELECT e.event_id,e.event_time_utc,e.competition_id,MAX(CASE WHEN ep.side='A' THEN ep.team_id END),MAX(CASE WHEN ep.side='B' THEN ep.team_id END) FROM event e JOIN event_participant ep ON ep.event_id=e.event_id WHERE e.sport='football' AND e.event_time_utc>=? AND e.event_time_utc<=? AND e.status NOT IN ('COMPLETED','FINAL') GROUP BY e.event_id,e.event_time_utc,e.competition_id HAVING COUNT(DISTINCT ep.side)=2 ORDER BY e.event_time_utc""",(now.isoformat(),end)).fetchall()
    preds=[]
    for eid,et,comp,home,away in future:
        f=features(c,home,away,et); x=np.asarray([[f.get(k,np.nan) for k in feats]],dtype=float); p=final.predict_proba(x)[0]; names={}
        for side,pid in c.execute("SELECT side,participant_id FROM event_participant WHERE event_id=? ORDER BY side",(eid,)):
            z=c.execute("SELECT canonical_name FROM participant WHERE participant_id=?",(pid,)).fetchone(); names[side]=z[0] if z else 'Unknown'
        preds.append({'event_id':eid,'time_utc':et,'competition':comp,'home':names.get('A'),'away':names.get('B'),'home_win':float(p[0]),'draw':float(p[1]),'away_win':float(p[2]),'pick':['home','draw','away'][int(np.argmax(p))],'confidence':float(np.max(p))})
    out={'sport':'football','status':'TRAINED','model_version':version,'training_rows':len(rows),'features':len(feats),'metrics':results,'selection_gate':gate,'predictions':preds,'generated_at_utc':utc()}; (RESULTS/'football.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); (RESULTS/'football_predictions.json').write_text(json.dumps({'generated_at_utc':utc(),'predictions':preds},ensure_ascii=False,indent=2),encoding='utf-8'); c.close(); return out

if __name__=='__main__': print(json.dumps(train(),ensure_ascii=False,indent=2))
