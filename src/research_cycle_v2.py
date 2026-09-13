from __future__ import annotations
import hashlib, json, sqlite3, subprocess
from datetime import datetime, timezone
from pathlib import Path
import joblib, numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score,brier_score_loss,log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/db/sports_v45.sqlite'; MODELS=ROOT/'models/research'; RESULTS=ROOT/'results/research'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin')
POLICY={'valorant':('rating','acs','adr','kast','k_d','fk_fd'),'basketball':('points','rebounds','assists','steals','blocks','turnovers','fieldGoalPct','threePointPct','freeThrowPct'),'volleyball':('attack','serve','receive','block','error','sideout'),'tennis':('ace','double_fault','first_serve','first_serve_points_won','break_points_saved','break_points_won'),'ufc':('sig_str','takedown','td_pct','sub_attempts','control_time'),'rizin':('sig_str','takedown','td_pct','sub_attempts','control_time')}

def utc(): return datetime.now(timezone.utc).isoformat()
def h(x): return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()[:16]
def ece(y,p,bins=10):
 y=np.asarray(y);p=np.asarray(p);z=0.
 for lo,hi in zip(np.linspace(0,1,bins,endpoint=False),np.linspace(0,1,bins)):
  m=(p>=lo)&(p<hi if hi<1 else p<=hi)
  if m.any(): z+=m.mean()*abs(y[m].mean()-p[m].mean())
 return float(z)
class TemporalCal:
 def __init__(self,base): self.base=base;self.cal=None
 def fit(self,X,y):
  n=len(y);s=max(20,int(n*.8))
  if s>=n or len(np.unique(y[:s]))<2:self.base.fit(X,y);self.cal=None;return self
  self.base.fit(X[:s],y[:s]);r=np.clip(self.base.predict_proba(X[s:])[:,1],1e-6,1-1e-6);yy=y[s:]
  if len(np.unique(yy))<2:self.cal=None;return self
  z=np.log(r/(1-r)).reshape(-1,1);self.cal=LogisticRegression(max_iter=1000).fit(z,yy);return self
 def predict_proba(self,X):
  r=np.clip(self.base.predict_proba(X)[:,1],1e-6,1-1e-6)
  if self.cal is None:p=r
  else:p=self.cal.predict_proba(np.log(r/(1-r)).reshape(-1,1))[:,1]
  return np.c_[1-p,p]
def pool(seed=42):
 b={'logistic':Pipeline([('imp',SimpleImputer(strategy='median')),('scale',StandardScaler()),('m',LogisticRegression(C=1,max_iter=3000,random_state=seed))]),'extra_trees':Pipeline([('imp',SimpleImputer(strategy='median')),('m',ExtraTreesClassifier(n_estimators=350,min_samples_leaf=4,max_features='sqrt',random_state=seed,n_jobs=-1,class_weight='balanced'))]),'random_forest':Pipeline([('imp',SimpleImputer(strategy='median')),('m',RandomForestClassifier(n_estimators=350,min_samples_leaf=4,max_features='sqrt',random_state=seed,n_jobs=-1,class_weight='balanced'))]),'hist_gb':Pipeline([('imp',SimpleImputer(strategy='median')),('m',HistGradientBoostingClassifier(max_iter=300,learning_rate=.035,l2_regularization=1.0,random_state=seed))])}
 return {k:TemporalCal(v) for k,v in b.items()}
def stat_cols(c,sport):
 w=POLICY[sport];q=','.join('?'*len(w));return [r[0] for r in c.execute(f'SELECT stat_name FROM match_stats WHERE sport=? AND stat_name IN ({q}) GROUP BY stat_name ORDER BY stat_name',(sport,*w)).fetchall()]
def load_pairs(c,sport):
 rows=c.execute("SELECT e.event_id,e.event_time_utc,ep.participant_id,ep.side FROM event e JOIN event_participant ep ON ep.event_id=e.event_id WHERE e.sport=? AND ep.side IN ('A','B') AND ep.participant_id IS NOT NULL ORDER BY e.event_time_utc,e.event_id,ep.side",(sport,)).fetchall();pairs={}
 for eid,et,pid,side in rows:pairs.setdefault(eid,{'time':et})[side]=pid
 return pairs
def load_eligible_outcomes(c,sport,pairs):
 q="""SELECT e.event_id,e.event_time_utc,o.outcome,ss.source_available_at_utc FROM event e JOIN event_outcome o ON o.event_id=e.event_id AND o.outcome_status='VERIFIED' AND o.outcome IN ('A','B') JOIN source_snapshot ss ON ss.source=o.source AND ss.source_url=o.source_url WHERE e.sport=? AND ss.availability_status='EXACT' AND ss.source_available_at_utc IS NOT NULL AND ss.source_available_at_utc <= datetime(e.event_time_utc,'-60 minutes') ORDER BY e.event_time_utc,e.event_id"""
 out=[]
 for eid,et,outcome,avail in c.execute(q,(sport,)).fetchall():
  p=pairs.get(eid)
  if p and 'A' in p and 'B' in p:out.append((eid,et,p['A'],p['B'],outcome,avail))
 return out
def build_rows(c,sport):
 cols=stat_cols(c,sport);pairs=load_pairs(c,sport);eligible=load_eligible_outcomes(c,sport,pairs);eligible_by_id={x[0]:x for x in eligible};ratings={};counts={};last={};rows=[];events=sorted(((eid,p['time']) for eid,p in pairs.items()),key=lambda x:(x[1],x[0]))
 for eid,et in events:
  for heid,ht,a,b,o,_ in eligible:
   if ht>=et: break
   ra=ratings.get(a,1500.);rb=ratings.get(b,1500.);exp=1/(1+10**((rb-ra)/400));act=1. if o=='A' else 0.;ratings[a]=ra+24*(act-exp);ratings[b]=rb+24*((1-act)-(1-exp));counts[a]=counts.get(a,0)+1;counts[b]=counts.get(b,0)+1;last[a]=ht;last[b]=ht
  if eid not in eligible_by_id:continue
  o=eligible_by_id[eid][4];p=pairs[eid];feat={}
  for side,pid in (('A',p['A']),('B',p['B'])):
   feat[f'{side}__elo']=ratings.get(pid,1500.);feat[f'{side}__history_n']=counts.get(pid,0)
   if pid in last:
    t0=datetime.fromisoformat(last[pid].replace('Z','+00:00'));t1=datetime.fromisoformat(et.replace('Z','+00:00'));feat[f'{side}__rest_days']=(t1-t0).total_seconds()/86400
   else:feat[f'{side}__rest_days']=np.nan
   for stat in cols:
    vals=c.execute("""SELECT ms.value_num FROM match_stats ms JOIN event pe ON pe.event_id=ms.event_id JOIN source_snapshot ss ON ss.source_url=ms.source_url AND ss.source=ms.source WHERE ms.sport=? AND ms.participant_id=? AND ms.stat_name=? AND pe.event_time_utc < ? AND ms.value_num IS NOT NULL AND ms.effective_at_utc IS NOT NULL AND ms.effective_at_utc <= datetime(?,'-60 minutes') AND ss.availability_status='EXACT' AND ss.source_available_at_utc IS NOT NULL AND ss.source_available_at_utc <= datetime(?,'-60 minutes') ORDER BY pe.event_time_utc DESC,ms.stat_id DESC LIMIT 20""",(sport,pid,stat,et,et,et)).fetchall();x=np.array([v[0] for v in vals],float)
    feat[f'{side}__{stat}__n']=len(x);feat[f'{side}__{stat}__mean']=float(x.mean()) if len(x) else np.nan;feat[f'{side}__{stat}__last']=float(x[0]) if len(x) else np.nan;feat[f'{side}__{stat}__std']=float(x.std()) if len(x)>1 else np.nan;feat[f'{side}__{stat}__trend']=float(x[0]-x[-1]) if len(x)>1 else np.nan
    if len(x):w=np.exp(-np.arange(len(x))/5);feat[f'{side}__{stat}__ewma5']=float((w*x).sum()/w.sum())
    else:feat[f'{side}__{stat}__ewma5']=np.nan
  for base in ('elo','history_n','rest_days'):
   a=feat.get(f'A__{base}',np.nan);b=feat.get(f'B__{base}',np.nan);feat[f'D__{base}']=a-b if np.isfinite(a) and np.isfinite(b) else np.nan
  for stat in cols:
   for suf in ('mean','last','std','trend','ewma5','n'):
    a=feat.get(f'A__{stat}__{suf}',np.nan);b=feat.get(f'B__{stat}__{suf}',np.nan);feat[f'D__{stat}__{suf}']=a-b if np.isfinite(a) and np.isfinite(b) else np.nan
  rows.append((eid,et,0 if o=='A' else 1,feat))
 return rows,sorted({k for _,_,_,f in rows for k in f})
def incumbent(c,sport):
 r=c.execute("SELECT model_version,metadata_json,artifact_path FROM model_state_snapshot WHERE sport=? AND market='winner' ORDER BY as_of_utc DESC LIMIT 1",(sport,)).fetchone()
 if not r:return None
 try:return {'version':r[0],'metadata':json.loads(r[1]),'artifact':r[2]}
 except Exception:return None
def score(y,p):
 y=np.asarray(y,int);p=np.asarray(p,float);return {'logloss':float(log_loss(y,np.c_[1-p,p],labels=[0,1])),'brier':float(brier_score_loss(y,p)),'accuracy':float(accuracy_score(y,(p>=.5).astype(int))),'ece':float(ece(y,p)),'n':int(len(y))}
def train_sport(sport):
 c=sqlite3.connect(DB);rows,features=build_rows(c,sport)
 if len(rows)<100:return {'sport':sport,'status':'DEFERRED','reason':'insufficient_strict_PIT_training_rows','rows':len(rows),'features':len(features)}
 X=np.array([[r[3].get(f,np.nan) for f in features] for r in rows],float);y=np.array([r[2] for r in rows],int);sel=max(60,int(len(rows)*.78))
 if len(rows)-sel<20 or len(np.unique(y[sel:]))<2:return {'sport':sport,'status':'DEFERRED','reason':'insufficient_locked_holdout','rows':len(rows),'selection_rows':sel,'holdout_rows':len(rows)-sel}
 results=[];start=max(50,int(sel*.70));step=max(10,min(30,sel-start))
 for name in pool():
  pr=[];tr=[];folds=[]
  for end in range(start,sel,step):
   te=min(end+step,sel)
   if te<=end or len(np.unique(y[:end]))<2:continue
   m=pool()[name];m.fit(X[:end],y[:end]);p=m.predict_proba(X[end:te])[:,1];pr+=p.tolist();tr+=y[end:te].tolist();folds.append({'train_end':rows[end-1][1],'test_start':rows[end][1],'test_end':rows[te-1][1],'n':te-end})
  if len(tr)>=20 and len(set(tr))>1:
   z=score(tr,pr);z.update({'model':name,'folds':folds});results.append(z)
 if not results:return {'sport':sport,'status':'DEFERRED','reason':'no_valid_selection_folds','rows':len(rows)}
 results.sort(key=lambda z:(z['logloss'],z['brier'],z['ece']));best=results[0]['model'];m=pool()[best];m.fit(X[:sel],y[:sel]);hp=m.predict_proba(X[sel:])[:,1];hold=score(y[sel:],hp);hold['model']=best
 if hold['ece']>.20:return {'sport':sport,'status':'REJECTED_HOLDOUT_CALIBRATION','holdout_metrics':hold,'selection':results[0]}
 inc=incumbent(c,sport);old=inc['metadata'].get('holdout_metrics') if inc else None;accept=True;gate='initial_model_locked_holdout'
 if old:
  tol=max(.002,.01*float(old.get('logloss',1e9)));accept=hold['logloss']<=float(old['logloss'])-tol;gate=f'challenger_locked_holdout_logloss={hold["logloss"]:.6f}; incumbent_locked_holdout_logloss={float(old["logloss"]):.6f}; required_improvement={tol:.6f}'
 if not accept:return {'sport':sport,'status':'REJECTED_CHALLENGER','reason':gate,'holdout_metrics':hold,'selection':results[0]}
 final=pool()[best];final.fit(X,y);version=h({'sport':sport,'features':features,'model':best,'rows':len(rows),'last_event':rows[-1][1],'selection':results[0],'holdout':hold});MODELS.mkdir(parents=True,exist_ok=True);RESULTS.mkdir(parents=True,exist_ok=True);artifact=MODELS/f'{sport}_current.joblib';joblib.dump({'model':final,'features':features,'sport':sport,'model_version':version,'training_rows':len(rows)},artifact);gitsha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip() or None;meta={'sport':sport,'market':'winner','model_version':version,'feature_version':'strict-pit-v9-elo-history-locked-holdout-temporal-calibration','training_cutoff_utc':rows[-1][1],'git_commit_sha':gitsha,'artifact_path':str(artifact.relative_to(ROOT)),'quality_status':'ACCEPTED_LOCKED_HOLDOUT','selection_gate':gate,'selection_metrics':results,'holdout_metrics':hold};c.execute('INSERT INTO model_state_snapshot(snapshot_id,sport,market,as_of_utc,model_version,feature_version,training_cutoff_utc,dataset_hash,git_commit_sha,artifact_path,quality_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(h(meta),sport,'winner',utc(),version,meta['feature_version'],rows[-1][1],h([(r[0],r[1],r[2]) for r in rows]),gitsha,str(artifact.relative_to(ROOT)),'ACCEPTED_LOCKED_HOLDOUT',json.dumps(meta,ensure_ascii=False)));c.commit();c.close();out={'sport':sport,'status':'TRAINED','model':best,'model_version':version,'training_rows':len(rows),'features':len(features),'selection_metrics':results,'holdout_metrics':hold,'selection_gate':gate};(RESULTS/f'{sport}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');return out
def main():
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('--sport',choices=SPORTS);a=ap.parse_args();sports=[a.sport] if a.sport else SPORTS;print(json.dumps([train_sport(s) for s in sports],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
