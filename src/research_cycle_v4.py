from __future__ import annotations
import hashlib,json,sqlite3,subprocess
from datetime import datetime,timezone,timedelta
from bisect import bisect_right
from pathlib import Path
import joblib,numpy as np
from sklearn.ensemble import ExtraTreesClassifier,HistGradientBoostingClassifier,RandomForestClassifier
try:
 from lightgbm import LGBMClassifier
except Exception:
 LGBMClassifier=None
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score,brier_score_loss,log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
ROOT=Path(__file__).resolve().parents[1];DB=ROOT/'data/db/sports_v45.sqlite';MODELS=ROOT/'models/research';RESULTS=ROOT/'results/research';SPORTS=('valorant','basketball','volleyball','ufc','rizin')
POLICY={'valorant':('rating','acs','adr','kast','k_d','fk_fd'),'basketball':('points','rebounds','assists','steals','blocks','turnovers','fieldGoalPct','threePointPct','freeThrowPct'),'volleyball':('attack','serve','receive','block','error','sideout'),'tennis':('ace','double_fault','first_serve','first_serve_points_won','break_points_saved','break_points_won'),'ufc':('sig_str','takedown','td_pct','sub_attempts','control_time'),'rizin':('sig_str','takedown','td_pct','sub_attempts','control_time'),'f1':(),'rugby':()}
def utc():return datetime.now(timezone.utc).isoformat()
def h(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()[:16]
def target_event(s,name,competition_id):
 n=(name or '').lower(); c=(competition_id or '').lower()
 if s=='basketball':
  return any(k in n or k in c for k in ('b.league','b league','bリーグ','asian games','アジア大会'))
 if s=='volleyball':
  return any(k in n or k in c for k in ('asian games','アジア大会'))
 return True
def ece(y,p,b=10):
 y=np.asarray(y);p=np.asarray(p);z=0
 for lo,hi in zip(np.linspace(0,1,b,endpoint=False),np.linspace(0,1,b)):
  m=(p>=lo)&(p<hi if hi<1 else p<=hi)
  if m.any():z+=m.mean()*abs(y[m].mean()-p[m].mean())
 return float(z)
class TC:
 def __init__(self,b):self.b=b;self.c=None
 def fit(self,X,y):
  s=max(20,int(len(y)*.8))
  if s>=len(y) or len(np.unique(y[:s]))<2:self.b.fit(X,y);self.c=None;return self
  self.b.fit(X[:s],y[:s]);r=np.clip(self.b.predict_proba(X[s:])[:,1],1e-6,1-1e-6)
  if len(np.unique(y[s:]))<2:self.c=None;return self
  self.c=LogisticRegression(max_iter=1000).fit(np.log(r/(1-r)).reshape(-1,1),y[s:]);return self
 def predict_proba(self,X):
  r=np.clip(self.b.predict_proba(X)[:,1],1e-6,1-1e-6);p=r if self.c is None else self.c.predict_proba(np.log(r/(1-r)).reshape(-1,1))[:,1];return np.c_[1-p,p]
def pool():
 return {k:TC(v) for k,v in {
  'logistic':Pipeline([('i',SimpleImputer(strategy='median')),('s',StandardScaler()),('m',LogisticRegression(max_iter=3000))]),
  'extra_trees':Pipeline([('i',SimpleImputer(strategy='median')),('m',ExtraTreesClassifier(n_estimators=350,min_samples_leaf=4,max_features='sqrt',n_jobs=-1,class_weight='balanced',random_state=42))]),
  'random_forest':Pipeline([('i',SimpleImputer(strategy='median')),('m',RandomForestClassifier(n_estimators=350,min_samples_leaf=4,max_features='sqrt',n_jobs=-1,class_weight='balanced',random_state=42))]),
  'hist_gb':Pipeline([('i',SimpleImputer(strategy='median')),('m',HistGradientBoostingClassifier(max_iter=300,learning_rate=.035,l2_regularization=1.0,max_leaf_nodes=31,random_state=42))]),
  'hist_gb_shallow':Pipeline([('i',SimpleImputer(strategy='median')),('m',HistGradientBoostingClassifier(max_iter=260,learning_rate=.045,l2_regularization=2.0,max_leaf_nodes=7,random_state=43))]),
  'hist_gb_fast':Pipeline([('i',SimpleImputer(strategy='median')),('m',HistGradientBoostingClassifier(max_iter=220,learning_rate=.055,l2_regularization=1.5,max_leaf_nodes=15,random_state=44))]),
  **({'lightgbm':Pipeline([('i',SimpleImputer(strategy='median')),('m',LGBMClassifier(n_estimators=360,learning_rate=.03,num_leaves=15,min_child_samples=35,subsample=.85,colsample_bytree=.85,reg_alpha=.1,reg_lambda=2.0,verbosity=-1,n_jobs=-1,random_state=45,deterministic=True,force_col_wise=True))])} if LGBMClassifier is not None else {})
 }.items()}
def pairmap(c,s):
 d={}
 for eid,t,p,side,comp in c.execute("SELECT e.event_id,e.event_time_utc,ep.participant_id,ep.side,e.competition_id FROM event e JOIN event_participant ep ON ep.event_id=e.event_id WHERE e.sport=? AND ep.side IN ('A','B') AND ep.participant_id IS NOT NULL ORDER BY e.event_time_utc,e.event_id,ep.side",(s,)).fetchall():
  if not t or not target_event(s,'',comp): continue
  d.setdefault(eid,{'time':t})[side]=p
 return d
def outcome_maps(c,s,pairs):
 labels={};hist=[]
 q="""SELECT e.event_id,e.event_time_utc,o.outcome,o.source,o.source_url,
                 (SELECT MIN(ss.source_available_at_utc)
                    FROM source_snapshot ss
                   WHERE ss.source=o.source
                     AND ss.source_url=o.source_url
                     AND ss.availability_status='EXACT'
                     AND ss.source_available_at_utc IS NOT NULL
                     AND (ss.event_time_utc IS NULL OR ss.event_time_utc=e.event_time_utc)) AS source_available_at_utc
          FROM event e
          JOIN event_outcome o
            ON o.event_id=e.event_id
           AND o.outcome_status='VERIFIED'
           AND o.outcome IN ('A','B')
         WHERE e.sport=?
         ORDER BY e.event_time_utc,e.event_id"""
 for eid,t,o,src,url,avail in c.execute(q,(s,)).fetchall():
  p=pairs.get(eid)
  if not p or 'A' not in p or 'B' not in p:continue
  labels[eid]=o
  status='EXACT' if avail else None
  if status=='EXACT' and avail:
   try:
    if datetime.fromisoformat(avail.replace('Z','+00:00'))<=datetime.fromisoformat(t.replace('Z','+00:00'))-__import__('datetime').timedelta(minutes=60):hist.append((eid,t,p['A'],p['B'],o))
   except Exception:pass
 return labels,hist
def statcols(c,s):
 w=POLICY[s];q=','.join('?'*len(w));return [r[0] for r in c.execute(f'SELECT stat_name FROM match_stats WHERE sport=? AND stat_name IN ({q}) GROUP BY stat_name',(s,*w)).fetchall()]
def _make_stat_history_loader(c,s):
 cache={}
 def load(pid,st):
  key=(pid,st)
  if key not in cache:
   rows=c.execute("""SELECT value_num,event_time_utc,effective_at_utc,source_available_at_utc
                      FROM (
                        SELECT ms.value_num,pe.event_time_utc,ms.effective_at_utc,
                               (SELECT MIN(ss.source_available_at_utc)
                                  FROM source_snapshot ss
                                 WHERE ss.source=ms.source
                                   AND ss.source_url=ms.source_url
                                   AND ss.availability_status='EXACT'
                                   AND ss.source_available_at_utc IS NOT NULL
                                   AND (ss.event_time_utc IS NULL OR ss.event_time_utc=pe.event_time_utc)) AS source_available_at_utc,
                               ROW_NUMBER() OVER (
                                 PARTITION BY ms.event_id
                                 ORDER BY ms.stat_id DESC
                               ) AS rn
                          FROM match_stats ms
                          JOIN event pe ON pe.event_id=ms.event_id
                         WHERE ms.sport=?
                           AND ms.participant_id=?
                           AND ms.stat_name=?
                           AND ms.value_num IS NOT NULL
                           AND ms.effective_at_utc IS NOT NULL
                      )
                     WHERE rn=1 AND source_available_at_utc IS NOT NULL
                     ORDER BY event_time_utc ASC""",(s,pid,st)).fetchall()
   prepared=[]
   times=[]
   for value,et,eff,src_avail in rows:
    try:
     et_dt=datetime.fromisoformat(str(et).replace('Z','+00:00'))
     eff_dt=datetime.fromisoformat(str(eff).replace('Z','+00:00'))
     avail_dt=datetime.fromisoformat(str(src_avail).replace('Z','+00:00'))
    except Exception:
     continue
    et_ts=et_dt.timestamp(); eff_ts=eff_dt.timestamp(); avail_ts=avail_dt.timestamp()
    prepared.append((et_ts,float(value),eff_ts,avail_ts))
    times.append(et_ts)
   cache[key]=(times,prepared)
  return cache[key]
 def history(pid,st,event_time,cutoff_dt):
  times,prepared=load(pid,st)
  event_ts=datetime.fromisoformat(str(event_time).replace('Z','+00:00')).timestamp()
  cutoff_ts=cutoff_dt.timestamp()
  idx=bisect_right(times,event_ts)-1
  out=[]
  for i in range(idx,-1,-1):
   et_ts,value,eff_ts,avail_ts=prepared[i]
   if et_ts>=event_ts:
    continue
   if eff_ts<=cutoff_ts and avail_ts<=cutoff_ts:
    out.append((value,datetime.fromtimestamp(et_ts,timezone.utc).isoformat(),datetime.fromtimestamp(avail_ts,timezone.utc).isoformat()))
    if len(out)>=20:
     break
  return out
 return history,cache

def build(c,s,include_unlabeled=False):
 pairs=pairmap(c,s);labels,hist=outcome_maps(c,s,pairs);cols=statcols(c,s);ratings={};ratings_fast={};ratings_slow={};counts={};last={};recent_results={};recent_times={};recent_opponent_elo={};h2h={};stat_history,stat_cache=_make_stat_history_loader(c,s);j=0;rows=[]
 for eid,t in sorted(((e,p['time']) for e,p in pairs.items()),key=lambda x:(x[1],x[0])):
  while j<len(hist) and hist[j][1]<t:
   _,_,a,b,o=hist[j]
   ra=ratings.get(a,1500.);rb=ratings.get(b,1500.)
   raf=ratings_fast.get(a,1500.);rbf=ratings_fast.get(b,1500.)
   ras=ratings_slow.get(a,1500.);rbs=ratings_slow.get(b,1500.)
   act=1 if o=='A' else 0
   exp=1/(1+10**((rb-ra)/400));expf=1/(1+10**((rbf-raf)/400));exps=1/(1+10**((rbs-ras)/400))
   ratings[a]=ra+24*(act-exp);ratings[b]=rb+24*((1-act)-(1-exp))
   ratings_fast[a]=raf+36*(act-expf);ratings_fast[b]=rbf+36*((1-act)-(1-expf))
   ratings_slow[a]=ras+12*(act-exps);ratings_slow[b]=rbs+12*((1-act)-(1-exps))
   counts[a]=counts.get(a,0)+1;counts[b]=counts.get(b,0)+1
   last[a]=hist[j][1];last[b]=hist[j][1]
   recent_results.setdefault(a,[]).append(act)
   recent_results.setdefault(b,[]).append(1-act)
   recent_results[a]=recent_results[a][-20:];recent_results[b]=recent_results[b][-20:]
   result_time=hist[j][1]
   recent_times.setdefault(a,[]).append(result_time); recent_times.setdefault(b,[]).append(result_time)
   recent_times[a]=recent_times[a][-100:]; recent_times[b]=recent_times[b][-100:]
   recent_opponent_elo.setdefault(a,[]).append(rb)
   recent_opponent_elo.setdefault(b,[]).append(ra)
   recent_opponent_elo[a]=recent_opponent_elo[a][-20:]; recent_opponent_elo[b]=recent_opponent_elo[b][-20:]
   key=tuple(sorted((a,b)))
   first_win=(act==1) if a==key[0] else (1-act)==1
   h2h.setdefault(key,[]).append(1 if first_win else 0)
   h2h[key]=h2h[key][-20:]
   j+=1
  if eid not in labels and not include_unlabeled:continue
  p=pairs[eid];f={};strict_evidence=0
  # Do not count default Elo/median-imputation rows as strict PIT evidence.
  # A row must contain at least one feature value whose source was observable
  # at least 60 minutes before the prediction cutoff, or a provenance-verified
  # historical outcome used to construct the rolling state.
  for side,pid in (('A',p['A']),('B',p['B'])):
   f[f'{side}__elo']=ratings.get(pid,1500.)
   f[f'{side}__elo_fast']=ratings_fast.get(pid,1500.)
   f[f'{side}__elo_slow']=ratings_slow.get(pid,1500.)
   f[f'{side}__elo_momentum']=f[f'{side}__elo_fast']-f[f'{side}__elo_slow']
   f[f'{side}__history_n']=counts.get(pid,0)
   f[f'{side}__rest_days']=((datetime.fromisoformat(t.replace('Z','+00:00'))-datetime.fromisoformat(last[pid].replace('Z','+00:00'))).total_seconds()/86400) if pid in last else np.nan
   event_dt=datetime.fromisoformat(t.replace('Z','+00:00'))
   rt=recent_times.get(pid,[])
   for dn in (7,14,30):
    f[f'{side}__games_last_{dn}d']=float(sum(datetime.fromisoformat(z.replace('Z','+00:00'))>=event_dt-timedelta(days=dn) for z in rt))
   f[f'{side}__short_rest_flag']=1.0 if np.isfinite(f[f'{side}__rest_days']) and f[f'{side}__rest_days']<2.0 else 0.0
   rr=recent_results.get(pid,[])
   for rn in (5,10,20):
    f[f'{side}__recent_winrate_{rn}']=float(np.mean(rr[-rn:])) if rr[-rn:] else np.nan
   f[f'{side}__recent_form_delta']=f[f'{side}__recent_winrate_5']-f[f'{side}__recent_winrate_20'] if np.isfinite(f[f'{side}__recent_winrate_5']) and np.isfinite(f[f'{side}__recent_winrate_20']) else np.nan
   relo=recent_opponent_elo.get(pid,[])
   for rn in (5,10,20):
    f[f'{side}__opponent_elo_mean_{rn}']=float(np.mean(relo[-rn:])) if relo[-rn:] else np.nan
   f[f'{side}__opponent_elo_delta']=f[f'{side}__opponent_elo_mean_5']-f[f'{side}__opponent_elo_mean_20'] if np.isfinite(f[f'{side}__opponent_elo_mean_5']) and np.isfinite(f[f'{side}__opponent_elo_mean_20']) else np.nan
   for st in cols:
    pred_dt=datetime.fromisoformat(t.replace('Z','+00:00'))
    cutoff_dt=pred_dt-__import__('datetime').timedelta(minutes=60)
    v=stat_history(pid,st,t,cutoff_dt)
    strict_evidence += len(v)
    x=np.array([z[0] for z in v],float)
    times=[datetime.fromisoformat(z[1].replace('Z','+00:00')) for z in v if z[1]]
    ages=np.array([max(0.0,(pred_dt-z).total_seconds()/86400.0) for z in times],float)
    w=np.exp(-np.arange(len(x))/5) if len(x) else np.array([])
    f[f'{side}__{st}__n']=len(x)
    f[f'{side}__{st}__mean']=float(x.mean()) if len(x) else np.nan
    f[f'{side}__{st}__median']=float(np.median(x)) if len(x) else np.nan
    f[f'{side}__{st}__q25']=float(np.quantile(x,.25)) if len(x) else np.nan
    f[f'{side}__{st}__q75']=float(np.quantile(x,.75)) if len(x) else np.nan
    f[f'{side}__{st}__iqr']=float(np.quantile(x,.75)-np.quantile(x,.25)) if len(x) else np.nan
    f[f'{side}__{st}__last']=float(x[0]) if len(x) else np.nan
    f[f'{side}__{st}__std']=float(x.std()) if len(x)>1 else np.nan
    f[f'{side}__{st}__trend']=float(x[0]-x[-1]) if len(x)>1 else np.nan
    f[f'{side}__{st}__ewma5']=float((w*x).sum()/w.sum()) if len(x) else np.nan
    f[f'{side}__{st}__age_days']=float(ages[0]) if len(ages) else np.nan
  for k in ('elo','elo_fast','elo_slow','history_n','rest_days','games_last_7d','games_last_14d','games_last_30d','short_rest_flag'):
   a=f[f'A__{k}'];b=f[f'B__{k}'];f[f'D__{k}']=a-b if np.isfinite(a) and np.isfinite(b) else np.nan
  for k in ('recent_winrate_5','recent_winrate_10','recent_winrate_20','recent_form_delta'):
   a=f[f'A__{k}'];b=f[f'B__{k}'];f[f'D__{k}']=a-b if np.isfinite(a) and np.isfinite(b) else np.nan
  for k in ('opponent_elo_mean_5','opponent_elo_mean_10','opponent_elo_mean_20','opponent_elo_delta'):
   a=f[f'A__{k}'];b=f[f'B__{k}'];f[f'D__{k}']=a-b if np.isfinite(a) and np.isfinite(b) else np.nan
  f['D__elo_momentum']= (f['A__elo_momentum']-f['B__elo_momentum']) if np.isfinite(f['A__elo_momentum']) and np.isfinite(f['B__elo_momentum']) else np.nan
  key=tuple(sorted((p['A'],p['B'])))
  hh=h2h.get(key,[])
  a_first=(p['A']==key[0])
  if hh:
   for rn in (5,20):
    vals=hh[-rn:]
    first_wr=float(np.mean(vals))
    a_wr=first_wr if a_first else 1.0-first_wr
    f[f'D__h2h_winrate_{rn}']=2.0*a_wr-1.0
   f['D__h2h_matches']=float(len(hh))
  else:
   f['D__h2h_winrate_5']=np.nan;f['D__h2h_winrate_20']=np.nan;f['D__h2h_matches']=0.0
  for st in cols:
   for suf in ('mean','median','q25','q75','iqr','last','std','trend','ewma5','n','age_days'):
    a=f[f'A__{st}__{suf}'];b=f[f'B__{st}__{suf}'];f[f'D__{st}__{suf}']=a-b if np.isfinite(a) and np.isfinite(b) else np.nan
   for base_suf in ('mean','median','last','ewma5'):
    a=f[f'A__{st}__{base_suf}'];b=f[f'B__{st}__{base_suf}']
    denom=abs(a)+abs(b)+1e-6 if np.isfinite(a) and np.isfinite(b) else np.nan
    f[f'D__{st}__{base_suf}_relative']=(a-b)/denom if np.isfinite(denom) else np.nan
  # counts is already updated only with outcomes strictly before the current event.
  # Reuse it instead of scanning the entire historical outcome list per event.
  prior_hist=(counts.get(p['A'],0)>0 or counts.get(p['B'],0)>0)
  if strict_evidence == 0 and not prior_hist:
   continue
  rows.append((eid,t,(0 if labels[eid]=='A' else 1) if eid in labels else None,f))
 return rows,sorted({k for _,_,_,f in rows for k in f})
def metric(y,p):
 y=np.asarray(y,int);p=np.asarray(p,float);return {'logloss':float(log_loss(y,np.c_[1-p,p],labels=[0,1])),'brier':float(brier_score_loss(y,p)),'accuracy':float(accuracy_score(y,p>=.5)),'ece':float(ece(y,p)),'n':len(y)}
def train(s):
 c=sqlite3.connect(DB);rows,fs=build(c,s)
 if len(rows)<100:return {'sport':s,'status':'DEFERRED','reason':'insufficient_strict_PIT_training_rows','rows':len(rows),'features':len(fs),'provenance_rule':'pre-cutoff observed feature or provenance-verified historical outcome required'}
 X=np.array([[r[3].get(f,np.nan) for f in fs] for r in rows]);y=np.array([r[2] for r in rows]);sel=max(60,int(len(rows)*.78))
 if len(rows)-sel<20 or len(np.unique(y[sel:]))<2:return {'sport':s,'status':'DEFERRED','reason':'insufficient_locked_holdout','rows':len(rows),'holdout_rows':len(rows)-sel}
 res=[];start=max(50,int(sel*.70));step=max(10,min(30,sel-start))
 for name in pool():
  pr=[];tr=[]
  for end in range(start,sel,step):
   te=min(end+step,sel)
   if len(np.unique(y[:end]))<2:continue
   m=pool()[name];m.fit(X[:end],y[:end]);pr+=m.predict_proba(X[end:te])[:,1].tolist();tr+=y[end:te].tolist()
  if len(tr)>=20 and len(set(tr))>1:z=metric(tr,pr);z['model']=name;res.append(z)
 if not res:return {'sport':s,'status':'DEFERRED','reason':'no_valid_selection_folds','rows':len(rows)}
 res.sort(key=lambda z:(z['logloss'],z['brier'],z['ece']));best=res[0]['model'];m=pool()[best];m.fit(X[:sel],y[:sel]);hold=metric(y[sel:],m.predict_proba(X[sel:])[:,1]);hold['model']=best
 if hold['ece']>.20:return {'sport':s,'status':'REJECTED_HOLDOUT_CALIBRATION','holdout_metrics':hold,'selection':res[0]}
 old=None;r=c.execute("SELECT metadata_json FROM model_state_snapshot WHERE sport=? AND market='winner' ORDER BY as_of_utc DESC LIMIT 1",(s,)).fetchone()
 if r:
  try:old=json.loads(r[0]).get('holdout_metrics')
  except Exception:pass
 gate='initial_model_locked_holdout';ok=True
 if old:
  tol=max(.002,.01*float(old['logloss']));ok=hold['logloss']<=float(old['logloss'])-tol;gate=f'new={hold["logloss"]:.6f};old={float(old["logloss"]):.6f};required={tol:.6f}'
 if not ok:return {'sport':s,'status':'REJECTED_CHALLENGER','reason':gate,'holdout_metrics':hold,'selection':res[0]}
 final=pool()[best];final.fit(X[:sel],y[:sel]);ver=h({'sport':s,'features':fs,'model':best,'rows':len(rows),'last':rows[-1][1],'holdout':hold});MODELS.mkdir(parents=True,exist_ok=True);RESULTS.mkdir(parents=True,exist_ok=True);artifact=MODELS/f'{s}_current.joblib';joblib.dump({'model':final,'features':fs,'sport':s,'model_version':ver,'training_rows':len(rows)},artifact);sha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip();meta={'sport':s,'market':'winner','model_version':ver,'feature_version':'strict-pit-v12-provenance-eligible-rows-locked-holdout','training_cutoff_utc':rows[-1][1],'git_commit_sha':sha,'artifact_path':str(artifact.relative_to(ROOT)),'quality_status':'ACCEPTED_LOCKED_HOLDOUT','holdout_frozen':True,'production_fit_excludes_holdout':True,'selection_gate':gate,'selection_metrics':res,'holdout_metrics':hold};c.execute('INSERT INTO model_state_snapshot(snapshot_id,sport,market,as_of_utc,model_version,feature_version,training_cutoff_utc,dataset_hash,git_commit_sha,artifact_path,quality_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(h(meta),s,'winner',utc(),ver,meta['feature_version'],rows[-1][1],h([(r[0],r[1],r[2]) for r in rows]),sha,str(artifact.relative_to(ROOT)),'ACCEPTED_LOCKED_HOLDOUT',json.dumps(meta,ensure_ascii=False)));c.commit();c.close();out={'sport':s,'status':'TRAINED','model':best,'model_version':ver,'training_rows':len(rows),'features':len(fs),'selection_metrics':res,'holdout_metrics':hold,'selection_gate':gate};(RESULTS/f'{s}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));return out
def main():
 import argparse
 a=argparse.ArgumentParser();a.add_argument('--sport',choices=SPORTS);x=a.parse_args();print(json.dumps([train(s) for s in ([x.sport] if x.sport else SPORTS)],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
