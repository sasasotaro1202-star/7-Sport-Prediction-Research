from __future__ import annotations
import hashlib,json,sqlite3,subprocess
from datetime import datetime,timezone
from pathlib import Path
import joblib,numpy as np
from sklearn.ensemble import ExtraTreesClassifier,HistGradientBoostingClassifier,RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score,brier_score_loss,log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
ROOT=Path(__file__).resolve().parents[1];DB=ROOT/'data/db/sports_v45.sqlite';MODELS=ROOT/'models/research';RESULTS=ROOT/'results/research'
SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin')
POLICY={'valorant':('rating','acs','adr','kast','k_d','fk_fd'),'basketball':('points','rebounds','assists','steals','blocks','turnovers','fieldGoalPct','threePointPct','freeThrowPct'),'volleyball':('attack','serve','receive','block','error','sideout'),'tennis':('ace','double_fault','first_serve','first_serve_points_won','break_points_saved','break_points_won'),'ufc':('sig_str','takedown','td_pct','sub_attempts','control_time'),'rizin':('sig_str','takedown','td_pct','sub_attempts','control_time')}
def utc():return datetime.now(timezone.utc).isoformat()
def h(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()[:16]
def ece(y,p,b=10):
 y=np.asarray(y);p=np.asarray(p);z=0.
 for lo,hi in zip(np.linspace(0,1,b,endpoint=False),np.linspace(0,1,b)):
  m=(p>=lo)&(p<hi if hi<1 else p<=hi)
  if m.any():z+=m.mean()*abs(y[m].mean()-p[m].mean())
 return float(z)
class TC:
 def __init__(self,base):self.base=base;self.cal=None
 def fit(self,X,y):
  s=max(20,int(len(y)*.8))
  if s>=len(y) or len(np.unique(y[:s]))<2:self.base.fit(X,y);self.cal=None;return self
  self.base.fit(X[:s],y[:s]);r=np.clip(self.base.predict_proba(X[s:])[:,1],1e-6,1-1e-6)
  if len(np.unique(y[s:]))<2:self.cal=None;return self
  self.cal=LogisticRegression(max_iter=1000).fit(np.log(r/(1-r)).reshape(-1,1),y[s:]);return self
 def predict_proba(self,X):
  r=np.clip(self.base.predict_proba(X)[:,1],1e-6,1-1e-6);p=r if self.cal is None else self.cal.predict_proba(np.log(r/(1-r)).reshape(-1,1))[:,1];return np.c_[1-p,p]
def pool(seed=42):
 b={'logistic':Pipeline([('i',SimpleImputer(strategy='median')),('s',StandardScaler()),('m',LogisticRegression(C=1,max_iter=3000,random_state=seed))]),'extra_trees':Pipeline([('i',SimpleImputer(strategy='median')),('m',ExtraTreesClassifier(n_estimators=350,min_samples_leaf=4,max_features='sqrt',random_state=seed,n_jobs=-1,class_weight='balanced'))]),'random_forest':Pipeline([('i',SimpleImputer(strategy='median')),('m',RandomForestClassifier(n_estimators=350,min_samples_leaf=4,max_features='sqrt',random_state=seed,n_jobs=-1,class_weight='balanced'))]),'hist_gb':Pipeline([('i',SimpleImputer(strategy='median')),('m',HistGradientBoostingClassifier(max_iter=300,learning_rate=.035,l2_regularization=1.0,random_state=seed))])};return {k:TC(v) for k,v in b.items()}
def pairs(c,s):
 q=c.execute("SELECT e.event_id,e.event_time_utc,ep.participant_id,ep.side FROM event e JOIN event_participant ep ON ep.event_id=e.event_id WHERE e.sport=? AND ep.side IN ('A','B') AND ep.participant_id IS NOT NULL ORDER BY e.event_time_utc,e.event_id,ep.side",(s,)).fetchall();d={}
 for eid,t,p,side in q:d.setdefault(eid,{'time':t})[side]=p
 return d
def eligible(c,s,pairs):
 q="""SELECT e.event_id,e.event_time_utc,o.outcome FROM event e JOIN event_outcome o ON o.event_id=e.event_id AND o.outcome_status='VERIFIED' AND o.outcome IN ('A','B') JOIN source_snapshot ss ON ss.source=o.source AND ss.source_url=o.source_url WHERE e.sport=? AND ss.availability_status='EXACT' AND ss.source_available_at_utc IS NOT NULL AND ss.source_available_at_utc<=datetime(e.event_time_utc,'-60 minutes') ORDER BY e.event_time_utc,e.event_id"""
 out=[]
 for eid,t,o in c.execute(q,(s,)).fetchall():
  p=pairs.get(eid)
  if p and 'A' in p and 'B' in p:out.append((eid,t,p['A'],p['B'],o))
 return out
def stats(c,s):
 w=POLICY[s];q=','.join('?'*len(w));return [r[0] for r in c.execute(f'SELECT stat_name FROM match_stats WHERE sport=? AND stat_name IN ({q}) GROUP BY stat_name',(s,*w)).fetchall()]
def build(c,s):
 ps=pairs(c,s);eo=eligible(c,s,ps);ei={x[0]:x for x in eo};events=sorted(((k,v['time']) for k,v in ps.items()),key=lambda x:(x[1],x[0]));cols=stats(c,s);ratings={};counts={};last={};j=0;rows=[]
 for eid,t in events:
  while j<len(eo) and eo[j][1]<t:
   _,_,a,b,o=eo[j];ra=ratings.get(a,1500.);rb=ratings.get(b,1500.);exp=1/(1+10**((rb-ra)/400));act=1. if o=='A' else 0.;ratings[a]=ra+24*(act-exp);ratings[b]=rb+24*((1-act)-(1-exp));counts[a]=counts.get(a,0)+1;counts[b]=counts.get(b,0)+1;last[a]=eo[j][1];last[b]=eo[j][1];j+=1
  if eid not in ei:continue
  feat={};p=ps[eid]
  for side,pid in (('A',p['A']),('B',p['B'])):
   feat[f'{side}__elo']=ratings.get(pid,1500.);feat[f'{side}__history_n']=counts.get(pid,0);feat[f'{side}__rest_days']=((datetime.fromisoformat(t.replace('Z','+00:00'))-datetime.fromisoformat(last[pid].replace('Z','+00:00'))).total_seconds()/86400) if pid in last else np.nan
   for st in cols:
    v=c.execute("""SELECT ms.value_num FROM match_stats ms JOIN event pe ON pe.event_id=ms.event_id JOIN source_snapshot ss ON ss.source=ms.source AND ss.source_url=ms.source_url WHERE ms.sport=? AND ms.participant_id=? AND ms.stat_name=? AND pe.event_time_utc<? AND ms.value_num IS NOT NULL AND ms.effective_at_utc IS NOT NULL AND ms.effective_at_utc<=datetime(?,'-60 minutes') AND ss.availability_status='EXACT' AND ss.source_available_at_utc<=datetime(?,'-60 minutes') ORDER BY pe.event_time_utc DESC,ms.stat_id DESC LIMIT 20""",(s,pid,st,t,t,t)).fetchall();x=np.array([z[0] for z in v],float);feat[f'{side}__{st}__n']=len(x);feat[f'{side}__{st}__mean']=float(x.mean()) if len(x) else np.nan;feat[f'{side}__{st}__last']=float(x[0]) if len(x) else np.nan;feat[f'{side}__{st}__std']=float(x.std()) if len(x)>1 else np.nan;feat[f'{side}__{st}__trend']=float(x[0]-x[-1]) if len(x)>1 else np.nan;feat[f'{side}__{st}__ewma5']=float((np.exp(-np.arange(len(x))/5)*x).sum()/np.exp(-np.arange(len(x))/5).sum()) if len(x) else np.nan
  for base in ('elo','history_n','rest_days'):
   a=feat[f'A__{base}'];b=feat[f'B__{base}'];feat[f'D__{base}']=a-b if np.isfinite(a) and np.isfinite(b) else np.nan
  for st in cols:
   for suf in ('mean','last','std','trend','ewma5','n'):
    a=feat[f'A__{st}__{suf}'];b=feat[f'B__{st}__{suf}'];feat[f'D__{st}__{suf}']=a-b if np.isfinite(a) and np.isfinite(b) else np.nan
  rows.append((eid,t,0 if ei[eid][4]=='A' else 1,feat))
 return rows,sorted({k for _,_,_,f in rows for k in f})
def score(y,p):
 y=np.asarray(y,int);p=np.asarray(p,float);return {'logloss':float(log_loss(y,np.c_[1-p,p],labels=[0,1])),'brier':float(brier_score_loss(y,p)),'accuracy':float(accuracy_score(y,p>=.5)),'ece':float(ece(y,p)),'n':len(y)}
def incumbent(c,s):
 r=c.execute("SELECT model_version,metadata_json FROM model_state_snapshot WHERE sport=? AND market='winner' ORDER BY as_of_utc DESC LIMIT 1",(s,)).fetchone();return None if not r else {'version':r[0],'metadata':json.loads(r[1])}
def train(s):
 c=sqlite3.connect(DB);rows,features=build(c,s)
 if len(rows)<100:return {'sport':s,'status':'DEFERRED','reason':'insufficient_strict_PIT_training_rows','rows':len(rows),'features':len(features)}
 X=np.array([[r[3].get(f,np.nan) for f in features] for r in rows]);y=np.array([r[2] for r in rows]);sel=max(60,int(len(rows)*.78))
 if len(rows)-sel<20 or len(np.unique(y[sel:]))<2:return {'sport':s,'status':'DEFERRED','reason':'insufficient_locked_holdout','rows':len(rows)}
 res=[];start=max(50,int(sel*.70));step=max(10,min(30,sel-start))
 for name in pool():
  pr=[];tr=[]
  for end in range(start,sel,step):
   te=min(end+step,sel)
   if len(np.unique(y[:end]))<2:continue
   m=pool()[name];m.fit(X[:end],y[:end]);pr+=m.predict_proba(X[end:te])[:,1].tolist();tr+=y[end:te].tolist()
  if len(tr)>=20 and len(set(tr))>1:
   z=score(tr,pr);z['model']=name;res.append(z)
 if not res:return {'sport':s,'status':'DEFERRED','reason':'no_valid_selection_folds','rows':len(rows)}
 res.sort(key=lambda z:(z['logloss'],z['brier'],z['ece']));best=res[0]['model'];m=pool()[best];m.fit(X[:sel],y[:sel]);hold=score(y[sel:],m.predict_proba(X[sel:])[:,1]);hold['model']=best
 if hold['ece']>.20:return {'sport':s,'status':'REJECTED_HOLDOUT_CALIBRATION','holdout_metrics':hold,'selection':res[0]}
 inc=incumbent(c,s);old=inc['metadata'].get('holdout_metrics') if inc else None;gate='initial_model_locked_holdout';ok=True
 if old:
  tol=max(.002,.01*float(old['logloss']));ok=hold['logloss']<=float(old['logloss'])-tol;gate=f'new={hold["logloss"]:.6f};old={float(old["logloss"]):.6f};required={tol:.6f}'
 if not ok:return {'sport':s,'status':'REJECTED_CHALLENGER','reason':gate,'holdout_metrics':hold,'selection':res[0]}
 final=pool()[best];final.fit(X,y);ver=h({'sport':s,'features':features,'model':best,'rows':len(rows),'last':rows[-1][1],'selection':res[0],'holdout':hold});MODELS.mkdir(parents=True,exist_ok=True);RESULTS.mkdir(parents=True,exist_ok=True);artifact=MODELS/f'{s}_current.joblib';joblib.dump({'model':final,'features':features,'sport':s,'model_version':ver,'training_rows':len(rows)},artifact);meta={'sport':s,'market':'winner','model_version':ver,'feature_version':'strict-pit-v10-elo-history-locked-holdout','training_cutoff_utc':rows[-1][1],'git_commit_sha':subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip(),'artifact_path':str(artifact.relative_to(ROOT)),'quality_status':'ACCEPTED_LOCKED_HOLDOUT','selection_gate':gate,'selection_metrics':res,'holdout_metrics':hold};c.execute('INSERT INTO model_state_snapshot(snapshot_id,sport,market,as_of_utc,model_version,feature_version,training_cutoff_utc,dataset_hash,git_commit_sha,artifact_path,quality_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(h(meta),s,'winner',utc(),ver,meta['feature_version'],rows[-1][1],h([(r[0],r[1],r[2]) for r in rows]),meta['git_commit_sha'],str(artifact.relative_to(ROOT)),'ACCEPTED_LOCKED_HOLDOUT',json.dumps(meta,ensure_ascii=False)));c.commit();c.close();out={'sport':s,'status':'TRAINED','model':best,'model_version':ver,'training_rows':len(rows),'features':len(features),'selection_metrics':res,'holdout_metrics':hold,'selection_gate':gate};(RESULTS/f'{s}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));return out
def main():
 import argparse
 a=argparse.ArgumentParser();a.add_argument('--sport',choices=SPORTS);x=a.parse_args();print(json.dumps([train(s) for s in ([x.sport] if x.sport else SPORTS)],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
