from __future__ import annotations
import hashlib, json, subprocess, sqlite3, re
from datetime import datetime, timezone
from pathlib import Path
import joblib, numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'; MODELS=ROOT/'models/research'; RESULTS=ROOT/'results/research'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin')
POLICY={'valorant':('rating','acs','adr','kast','k_d','fk_fd'),'basketball':('points','rebounds','assists','steals','blocks','turnovers','fieldGoalPct','threePointPct','freeThrowPct'),'volleyball':('attack','serve','receive','block','error','sideout'),'tennis':('ace','double_fault','first_serve','first_serve_points_won','break_points_saved','break_points_won'),'ufc':('sig_str','takedown','td_pct','sub_attempts','control_time'),'rizin':('sig_str','takedown','td_pct','sub_attempts','control_time')}
FORBIDDEN=re.compile(r'(?:^|[._-])(result|results|outcome|winner|loser|score|position|rank|finish|method|round|time|placement)(?:$|[._-])',re.I)

def utc(): return datetime.now(timezone.utc).isoformat()
def h(x): return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()[:16]
def ece(y,p,bins=10):
    y=np.asarray(y); p=np.asarray(p); out=0.0
    for lo,hi in zip(np.linspace(0,1,bins,endpoint=False),np.linspace(0,1,bins)):
        m=(p>=lo)&(p<hi if hi<1 else p<=hi)
        if m.any(): out += m.mean()*abs(y[m].mean()-p[m].mean())
    return float(out)

class TemporalSigmoidCalibrated:
    def __init__(self,base,calibration_fraction=.20): self.base=base; self.calibration_fraction=calibration_fraction; self.calibrator=None
    def fit(self,X,y):
        n=len(y); split=max(20,int(n*(1-self.calibration_fraction)))
        if split>=n or len(np.unique(y[:split]))<2:self.base.fit(X,y);self.calibrator=None;return self
        self.base.fit(X[:split],y[:split]);raw=self.base.predict_proba(X[split:])[:,1];yy=np.asarray(y[split:],dtype=int)
        if len(np.unique(yy))<2:self.calibrator=None;return self
        eps=1e-6;z=np.log(np.clip(raw,eps,1-eps)/(1-np.clip(raw,eps,1-eps))).reshape(-1,1);self.calibrator=LogisticRegression(C=1.0,max_iter=1000);self.calibrator.fit(z,yy);return self
    def predict_proba(self,X):
        raw=self.base.predict_proba(X)[:,1]
        if self.calibrator is None:p=raw
        else:
            eps=1e-6;z=np.log(np.clip(raw,eps,1-eps)/(1-np.clip(raw,eps,1-eps))).reshape(-1,1);p=self.calibrator.predict_proba(z)[:,1]
        return np.column_stack([1-p,p])

def model_pool(seed=42):
    base={'logistic':Pipeline([('imp',SimpleImputer(strategy='median')),('scale',StandardScaler()),('model',LogisticRegression(max_iter=3000,C=1.0,random_state=seed))]),'extra_trees':Pipeline([('imp',SimpleImputer(strategy='median')),('model',ExtraTreesClassifier(n_estimators=400,min_samples_leaf=4,max_features='sqrt',random_state=seed,n_jobs=-1,class_weight='balanced'))]),'random_forest':Pipeline([('imp',SimpleImputer(strategy='median')),('model',RandomForestClassifier(n_estimators=400,min_samples_leaf=4,max_features='sqrt',random_state=seed,n_jobs=-1,class_weight='balanced'))]),'hist_gb':Pipeline([('imp',SimpleImputer(strategy='median')),('model',HistGradientBoostingClassifier(max_iter=300,learning_rate=.035,l2_regularization=1.0,random_state=seed))])}
    return {k:TemporalSigmoidCalibrated(v) for k,v in base.items()}

def stat_columns(c,sport):
    wanted=POLICY.get(sport,());q=','.join('?' for _ in wanted)
    if not wanted:return []
    rows=c.execute(f"SELECT stat_name,COUNT(*) FROM match_stats WHERE sport=? AND stat_name IN ({q}) GROUP BY stat_name ORDER BY COUNT(*) DESC",(sport,*wanted)).fetchall()
    return [r[0] for r in rows]

def _eligible_history(c,sport,cutoff):
    return c.execute("""SELECT e.event_id,e.event_time_utc,ep.participant_id,ep.side,o.outcome FROM event e
        JOIN event_participant ep ON ep.event_id=e.event_id AND ep.side IN ('A','B')
        JOIN event_outcome o ON o.event_id=e.event_id AND o.outcome_status='VERIFIED'
        JOIN source_snapshot ss ON ss.source=o.source AND ss.source_url=o.source_url
        WHERE e.sport=? AND e.event_time_utc IS NOT NULL AND e.event_time_utc < ?
          AND ss.availability_status='EXACT' AND ss.source_available_at_utc IS NOT NULL
          AND ss.source_available_at_utc <= datetime(?,'-60 minutes')
        ORDER BY e.event_time_utc,e.event_id,ep.side""",(sport,cutoff,cutoff)).fetchall()

def build_rows(c,sport):
    cols=stat_columns(c,sport); rows=[]
    events=c.execute("SELECT event_id,event_time_utc FROM event WHERE sport=? AND event_time_utc IS NOT NULL ORDER BY event_time_utc,event_id",(sport,)).fetchall()
    ratings={};counts={};last_time={}
    for eid,et in events:
        o=c.execute("SELECT outcome,source,source_url FROM event_outcome WHERE event_id=? AND outcome_status='VERIFIED' AND outcome IN ('A','B')",(eid,)).fetchone()
        ps=c.execute("SELECT participant_id,side FROM event_participant WHERE event_id=? AND side IN ('A','B') AND participant_id IS NOT NULL GROUP BY participant_id,side ORDER BY side",(eid,)).fetchall()
        if not o or len(ps)!=2:continue
        cutoff=et
        # Ratings are built only from prior outcomes whose source was provably available by this cutoff.
        hist=_eligible_history(c,sport,cutoff)
        if hist:
            ratings={};counts={};last_time={}
            for _,ht,pid,side,ho in hist:
                ra=ratings.get(pid,1500.0); opp=None
                # Find the opposing participant in the same historical event cheaply from the pair cache.
                pair=c.execute("SELECT participant_id,side FROM event_participant WHERE event_id=? AND side IN ('A','B') GROUP BY participant_id,side ORDER BY side",(_ ,)).fetchall()
                for opid,oside in pair:
                    if oside!=side:opp=opid;break
                rb=ratings.get(opp,1500.0) if opp else 1500.0
                expected=1/(1+10**((rb-ra)/400))
                actual=1.0 if (ho==side) else 0.0
                k=24.0
                ratings[pid]=ra+k*(actual-expected);counts[pid]=counts.get(pid,0)+1;last_time[pid]=ht
        feat={}
        for pid,side in ps:
            feat[f'{side}__elo']=float(ratings.get(pid,1500.0));feat[f'{side}__history_n']=float(counts.get(pid,0));
            prev=last_time.get(pid);feat[f'{side}__rest_days']=float((datetime.fromisoformat(et.replace('Z','+00:00'))-datetime.fromisoformat(prev.replace('Z','+00:00'))).total_seconds()/86400) if prev else np.nan
            for stat in cols:
                vals=c.execute("""SELECT ms.value_num FROM match_stats ms JOIN event pe ON pe.event_id=ms.event_id JOIN source_snapshot ss ON ss.source_url=ms.source_url AND ss.source=ms.source WHERE ms.sport=? AND ms.participant_id=? AND ms.stat_name=? AND pe.event_time_utc IS NOT NULL AND pe.event_time_utc < ? AND ms.value_num IS NOT NULL AND ms.effective_at_utc IS NOT NULL AND ms.effective_at_utc <= datetime(?,'-60 minutes') AND ss.availability_status='EXACT' AND ss.source_available_at_utc IS NOT NULL AND ss.source_available_at_utc <= datetime(?,'-60 minutes') ORDER BY pe.event_time_utc DESC,ms.stat_id DESC LIMIT 20""",(sport,pid,stat,et,et,et)).fetchall();x=np.asarray([v[0] for v in vals],dtype=float)
                feat[f'{side}__{stat}__n']=float(len(x));feat[f'{side}__{stat}__mean']=float(x.mean()) if len(x) else np.nan;feat[f'{side}__{stat}__last']=float(x[0]) if len(x) else np.nan;feat[f'{side}__{stat}__std']=float(x.std()) if len(x)>1 else np.nan;feat[f'{side}__{stat}__trend']=float(x[0]-x[-1]) if len(x)>1 else np.nan
                if len(x):w=np.exp(-np.arange(len(x))/5.0);feat[f'{side}__{stat}__ewma5']=float(np.sum(w*x)/np.sum(w))
                else:feat[f'{side}__{stat}__ewma5']=np.nan
        for base in ('elo','history_n','rest_days'):
            a=feat.get(f'A__{base}',np.nan);b=feat.get(f'B__{base}',np.nan);feat[f'D__{base}']=a-b if np.isfinite(a) and np.isfinite(b) else np.nan
        for stat in cols:
            for suffix in ('mean','last','std','trend','ewma5','n'):
                a=feat.get(f'A__{stat}__{suffix}',np.nan);b=feat.get(f'B__{stat}__{suffix}',np.nan);feat[f'D__{stat}__{suffix}']=a-b if np.isfinite(a) and np.isfinite(b) else np.nan
        av=sum(np.isfinite(v) for k,v in feat.items() if k.startswith('A__'));bv=sum(np.isfinite(v) for k,v in feat.items() if k.startswith('B__'))
        # Elo/history is a valid cold-start feature even when detailed stats are unavailable.
        if av==0 or bv==0:continue
        rows.append((eid,et,0 if o[0]=='A' else 1,feat))
    return rows,sorted({k for _,_,_,f in rows for k in f})

def incumbent(c,sport):
    r=c.execute("SELECT model_version,metadata_json,artifact_path FROM model_state_snapshot WHERE sport=? AND market='winner' ORDER BY as_of_utc DESC LIMIT 1",(sport,)).fetchone()
    if not r:return None
    try:return {'version':r[0],'metadata':json.loads(r[1]),'artifact':r[2]}
    except Exception:return None

def score(y,p):
    y=np.asarray(y,dtype=int);p=np.asarray(p,dtype=float);pred=(p>=.5).astype(int)
    return {'logloss':float(log_loss(y,np.column_stack([1-p,p]),labels=[0,1])),'brier':float(brier_score_loss(y,p)),'accuracy':float(accuracy_score(y,pred)),'ece':float(ece(y,p)),'n':int(len(y))}

def train_sport(sport):
    c=sqlite3.connect(DB);rows,features=build_rows(c,sport)
    if len(rows)<100 or len(features)<2:
        out={'sport':sport,'status':'DEFERRED','reason':'insufficient_strict_PIT_training_rows','rows':len(rows),'features':len(features),'timestamp_utc':utc()};c.close();return out
    X=np.array([[r[3].get(f,np.nan) for f in features] for r in rows],dtype=float);y=np.array([r[2] for r in rows],dtype=int);selection_end=max(60,int(len(rows)*.78));holdout_n=len(rows)-selection_end
    if holdout_n<20 or len(np.unique(y[selection_end:]))<2:
        out={'sport':sport,'status':'DEFERRED','reason':'insufficient_locked_holdout','rows':len(rows),'selection_rows':selection_end,'holdout_rows':holdout_n};c.close();return out
    selection_results=[];step=max(10,min(30,selection_end-max(50,int(selection_end*.70))))
    for name in model_pool():
        probs=[];truth=[];folds=[]
        for end in range(max(50,int(selection_end*.70)),selection_end,step):
            test_end=min(end+step,selection_end)
            if test_end<=end or len(np.unique(y[:end]))<2:continue
            model=model_pool()[name];model.fit(X[:end],y[:end]);p=model.predict_proba(X[end:test_end])[:,1];probs.extend(p.tolist());truth.extend(y[end:test_end].tolist());folds.append({'train_end':rows[end-1][1],'test_start':rows[end][1],'test_end':rows[test_end-1][1],'n':test_end-end})
        if len(truth)<20 or len(set(truth))<2:continue
        m=score(truth,probs);m.update({'model':name,'folds':folds});selection_results.append(m)
    if not selection_results:c.close();return {'sport':sport,'status':'DEFERRED','reason':'no_valid_selection_folds','rows':len(rows)}
    selection_results.sort(key=lambda z:(z['logloss'],z['brier'],z['ece']));best_name=selection_results[0]['model'];holdout_model=model_pool()[best_name];holdout_model.fit(X[:selection_end],y[:selection_end]);holdout_prob=holdout_model.predict_proba(X[selection_end:])[:,1];holdout=score(y[selection_end:],holdout_prob);holdout['model']=best_name
    if holdout['ece']>0.20:
        out={'sport':sport,'status':'REJECTED_HOLDOUT_CALIBRATION','reason':'locked_holdout_ece_above_gate','selection':selection_results[0],'holdout_metrics':holdout,'training_rows':len(rows)};c.close();RESULTS.mkdir(parents=True,exist_ok=True);(RESULTS/f'{sport}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');return out
    inc=incumbent(c,sport);accept=True;gate_reason='initial_model_locked_holdout';old_hold=inc['metadata'].get('holdout_metrics') if inc else None
    if old_hold:
        oldll=float(old_hold.get('logloss',1e9));newll=float(holdout['logloss']);tol=max(.002,.01*oldll);accept=newll<=oldll-tol;gate_reason=f'challenger_locked_holdout_logloss={newll:.6f}; incumbent_locked_holdout_logloss={oldll:.6f}; required_improvement={tol:.6f}'
    if not accept:
        out={'sport':sport,'status':'REJECTED_CHALLENGER','reason':gate_reason,'candidate_selection':selection_results[0],'holdout_metrics':holdout,'all_selection_models':selection_results,'training_rows':len(rows)};c.close();RESULTS.mkdir(parents=True,exist_ok=True);(RESULTS/f'{sport}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');return out
    final=model_pool()[best_name];final.fit(X,y);version=h({'sport':sport,'features':features,'model':best_name,'rows':len(rows),'last_event':rows[-1][1],'selection':selection_results[0],'holdout':holdout});MODELS.mkdir(parents=True,exist_ok=True);RESULTS.mkdir(parents=True,exist_ok=True);artifact=MODELS/f'{sport}_current.joblib';joblib.dump({'model':final,'features':features,'sport':sport,'model_version':version,'training_rows':len(rows)},artifact);gitsha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip() or None
    metadata={'sport':sport,'market':'winner','model_version':version,'feature_version':'strict-pit-v8-elo-history-locked-holdout-temporal-calibration','training_cutoff_utc':rows[-1][1],'git_commit_sha':gitsha,'artifact_path':str(artifact.relative_to(ROOT)),'quality_status':'ACCEPTED_LOCKED_HOLDOUT','selection_gate':gate_reason,'selection_metrics':selection_results,'holdout_metrics':holdout}
    c.execute('''INSERT INTO model_state_snapshot(snapshot_id,sport,market,as_of_utc,model_version,feature_version,training_cutoff_utc,dataset_hash,git_commit_sha,artifact_path,quality_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(h(metadata),sport,'winner',utc(),version,metadata['feature_version'],rows[-1][1],h([(r[0],r[1],r[2]) for r in rows]),gitsha,str(artifact.relative_to(ROOT)),'ACCEPTED_LOCKED_HOLDOUT',json.dumps(metadata,ensure_ascii=False)));c.commit();c.close();out={'sport':sport,'status':'TRAINED','model':best_name,'model_version':version,'training_rows':len(rows),'features':len(features),'selection_metrics':selection_results,'holdout_metrics':holdout,'selection_gate':gate_reason};(RESULTS/f'{sport}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');return out

def main():
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--sport',choices=SPORTS);a=ap.parse_args();sports=[a.sport] if a.sport else SPORTS;print(json.dumps([train_sport(s) for s in sports],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
