from __future__ import annotations
import argparse, json, os
from pathlib import Path
import arviz as az
import numpy as np
import pymc as pm
from src.research_policy import POLICY
MODEL_VERSION="pymc-wfo-v2-matched-control"
MIN_ROWS=300
def sigmoid(x): return 1.0/(1.0+np.exp(-np.clip(x,-40.0,40.0)))
def logloss(y,p):
    p=np.clip(p,1e-7,1.0-1e-7); return float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p)))
def brier(y,p): return float(np.mean((p-y)**2))
def ece(y,p,bins=10):
    edges=np.linspace(0.0,1.0,bins+1); out=0.0
    for i in range(bins):
        m=(p>=edges[i]) & ((p<edges[i+1]) if i<bins-1 else (p<=edges[i+1]))
        if m.any(): out+=float(m.mean())*abs(float(y[m].mean())-float(p[m].mean()))
    return out
def make_fold(rows,train_end,test_end,stats):
    train,test=rows[:train_end],rows[train_end:test_end]
    teams=sorted({str(r["team_a"]) for r in train}|{str(r["team_b"]) for r in train}); oov="__OOV_TEAM__"; teams.append(oov); ti={t:i for i,t in enumerate(teams)}
    def enc(sub):
        ta=[];tb=[];y=[];x=[];miss=[]
        for r in sub:
            f=r.get("features") or {}; vals=[]; flags=[]
            for s in stats:
                a=f.get(f"A__{s}__mean"); b=f.get(f"B__{s}__mean")
                if a is None or b is None: vals.append(np.nan); flags.append(1.0)
                else: vals.append(float(a)-float(b)); flags.append(0.0)
            ta.append(ti.get(str(r["team_a"]),ti[oov])); tb.append(ti.get(str(r["team_b"]),ti[oov])); y.append(1 if r["outcome"]=="A" else 0); x.append(vals); miss.append(flags)
        return np.asarray(ta,np.int64),np.asarray(tb,np.int64),np.asarray(y,np.int64),np.asarray(x,float),np.asarray(miss,float)
    ta,tb,y,x,m=enc(train); ta2,tb2,y2,x2,m2=enc(test)
    med=np.nanmedian(x,axis=0); med=np.where(np.isfinite(med),med,0.0); x=np.where(np.isfinite(x),x,med); x2=np.where(np.isfinite(x2),x2,med)
    mu=x.mean(axis=0); scale=x.std(axis=0); scale=np.where(scale>1e-8,scale,1.0)
    return train,test,teams,ta,tb,y,np.concatenate([(x-mu)/scale,m],1),ta2,tb2,y2,np.concatenate([(x2-mu)/scale,m2],1)
def fit_logistic_baseline(x,y,l2=1.0,steps=60):
    x=np.asarray(x,float); y=np.asarray(y,float)
    xb=np.concatenate([np.ones((len(x),1)),x],axis=1); w=np.zeros(xb.shape[1],float)
    reg=np.eye(xb.shape[1],dtype=float)*float(l2); reg[0,0]=0.0
    for _ in range(int(steps)):
        p=sigmoid(xb@w); wt=np.clip(p*(1-p),1e-6,None)
        h=(xb.T*wt)@xb+reg; g=xb.T@(p-y)+reg@w
        try: delta=np.linalg.solve(h,g)
        except np.linalg.LinAlgError: delta=np.linalg.pinv(h)@g
        w-=delta
        if float(np.max(np.abs(delta)))<1e-7: break
    return w
def logistic_predict(w,x):
    xb=np.concatenate([np.ones((len(x),1)),np.asarray(x,float)],axis=1)
    return sigmoid(xb@w)

def fit_fold(payload,draws,tune,seed):
    train,test,teams,ta,tb,y,x,ta2,tb2,y2,x2=payload
    with pm.Model(coords={"team":np.arange(len(teams)),"feature":np.arange(x.shape[1])}):
        a=pm.Data("team_a",ta); b=pm.Data("team_b",tb); z=pm.Data("x",x)
        sigma=pm.HalfNormal("sigma_strength",sigma=1.0); strength=pm.Normal("team_strength",mu=0.0,sigma=sigma,dims="team")
        intercept=pm.Normal("intercept",mu=0.0,sigma=1.0); beta=pm.Normal("beta",mu=0.0,sigma=1.0,dims="feature")
        centered=strength-pm.math.mean(strength)
        pm.Bernoulli("outcome",p=pm.math.sigmoid(intercept+centered[a]-centered[b]+pm.math.sum(z*beta,1)),observed=y)
        idata=pm.sample(draws=draws,tune=tune,chains=2,cores=2,random_seed=seed,target_accept=0.9,progressbar=False,return_inferencedata=True)
    post=idata.posterior; ic=np.asarray(post["intercept"].values); bc=np.asarray(post["beta"].values); tc=np.asarray(post["team_strength"].values); tc=tc-tc.mean(axis=-1,keepdims=True)
    p=sigmoid(ic[...,None]+tc[...,ta2]-tc[...,tb2]+np.einsum("scf,nf->scn",bc,x2)).mean((0,1)); base=np.full(len(y2),0.5)
    p_logistic=logistic_predict(fit_logistic_baseline(x,y),x2)
    summ=az.summary(idata,var_names=["intercept","sigma_strength"],round_to=6)
    return {"train_rows":len(train),"test_rows":len(test),"metrics":{"logloss":logloss(y2,p),"brier":brier(y2,p),"accuracy":float(np.mean((p>=0.5)==y2)),"ece":ece(y2,p),"baseline_0_5_logloss":logloss(y2,base),"baseline_0_5_brier":brier(y2,base),"matched_logistic_logloss":logloss(y2,p_logistic),"matched_logistic_brier":brier(y2,p_logistic),"matched_logistic_ece":ece(y2,p_logistic),"pymc_vs_matched_logistic_logloss_delta":float(logloss(y2,p_logistic)-logloss(y2,p))},"diagnostics":{"max_r_hat":float(summ["r_hat"].max()),"divergences":int(np.asarray(idata.sample_stats["diverging"]).sum()),"finite_probabilities":bool(np.isfinite(p).all())}}
def run(dataset,draws=250,tune=250,seed=7):
    if dataset.get("status")!="READY": return {"status":"BLOCKED_PIT_DATASET","dataset_status":dataset.get("status")}
    if dataset.get("dataset_scope")!="SPORT_SINGLE": raise ValueError("WFO requires SPORT_SINGLE dataset")
    rows=sorted(dataset.get("rows") or [],key=lambda r:(r["event_time_utc"],r["event_id"])); sport=dataset["active_sports"][0]
    if len(rows)<MIN_ROWS: return {"status":"BLOCKED_INSUFFICIENT_WFO_ROWS","sport":sport,"row_count":len(rows),"minimum_rows":MIN_ROWS}
    n=len(rows); width=max(50,n//10); folds=[]
    for i,end in enumerate([n-3*width,n-2*width,n-width],1):
        f=fit_fold(make_fold(rows,end,end+width,tuple(POLICY[sport])),draws,tune,seed+i); f.update({"fold":i,"train_end_index":end,"test_end_index":end+width,"chronological":True,"event_cluster_one_case":True}); folds.append(f)
    ll=np.asarray([f["metrics"]["logloss"] for f in folds])
    br=np.asarray([f["metrics"]["brier"] for f in folds])
    ac=np.asarray([f["metrics"]["accuracy"] for f in folds])
    es=np.asarray([f["metrics"]["ece"] for f in folds])
    mll=np.asarray([f["metrics"]["matched_logistic_logloss"] for f in folds])
    mbr=np.asarray([f["metrics"]["matched_logistic_brier"] for f in folds])
    mece=np.asarray([f["metrics"]["matched_logistic_ece"] for f in folds])
    deltas=np.asarray([f["metrics"]["pymc_vs_matched_logistic_logloss_delta"] for f in folds])
    candidate_ll=float(ll.mean()); matched_ll=float(mll.mean())
    candidate_br=float(br.mean()); matched_br=float(mbr.mean())
    folds_better=int(sum(f["metrics"]["logloss"]<f["metrics"]["matched_logistic_logloss"] for f in folds))
    rhat_max=float(max(f["diagnostics"]["max_r_hat"] for f in folds))
    div_total=int(sum(f["diagnostics"]["divergences"] for f in folds))
    finite=bool(all(f["diagnostics"]["finite_probabilities"] for f in folds))
    wfo_diagnostics_pass=bool(rhat_max<=1.05 and div_total==0 and finite and len(folds)>=3)
    return {
      "status":"WFO_PERFORMANCE_OBSERVED","candidate":"pymc-devs/pymc","model_version":MODEL_VERSION,"sport":sport,
      "dataset_sha256":dataset.get("dataset_sha256"),
      "github_head_sha":os.environ.get("GITHUB_SHA"),
      "reference_model":"matched_feature_logistic_diagnostic_only",
      "incumbent_model_id":None,
      "incumbent_comparison_verified":False,
      "production_dependency":False,"automatic_promotion":False,
      "data":{"rows":n,"fold_count":len(folds),"test_width":width,"chronological":True,"future_feature_leakage":False,"prediction_cutoff_before_outcome":True,"frozen_holdout_excluded":bool(dataset.get("frozen_holdout_excluded",False))},
      "aggregate":{
        "fold_count":len(folds),"logloss_mean":candidate_ll,"logloss_median":float(np.median(ll)),"logloss_worst":float(ll.max()),
        "brier_mean":candidate_br,"brier_worst":float(br.max()),"accuracy_mean":float(ac.mean()),"ece_mean":float(es.mean()),"ece_worst":float(es.max()),
        "matched_logistic_logloss_mean":matched_ll,"matched_logistic_brier_mean":matched_br,"matched_logistic_ece_mean":float(mece.mean()),
        "candidate_relative_logloss_improvement_vs_matched_control":float((matched_ll-candidate_ll)/max(abs(matched_ll),1e-9)),
        "candidate_secondary_relative_improvement_vs_matched_control":float((matched_br-candidate_br)/max(abs(matched_br),1e-9)),
        "pymc_vs_matched_logistic_logloss_delta_mean":float(deltas.mean()),"pymc_vs_matched_logistic_logloss_delta_worst":float(deltas.max()),
        "folds_better_than_0_5_logloss":int(sum(f["metrics"]["logloss"]<f["metrics"]["baseline_0_5_logloss"] for f in folds)),
        "folds_better_than_matched_logistic":folds_better,
      },
      "diagnostics":{"max_r_hat_across_folds":rhat_max,"total_divergences":div_total,"all_finite":finite,"wfo_diagnostics_pass":wfo_diagnostics_pass},
      "execution_verified":True,
      "performance_verification":False,
      "evidence_boundary":{"wfo_execution_verified":True,"wfo_diagnostics_pass":wfo_diagnostics_pass,"wfo_performance_verified":False,"production_dependency":False,"automatic_promotion":False,"promotion_status":"HOLD","required_next_gates":["matched incumbent WFO","calibration","ablation","robustness","frozen holdout","shadow comparison"]},
      "folds":folds}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--dataset",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); ap.add_argument("--draws",type=int,default=250); ap.add_argument("--tune",type=int,default=250); ap.add_argument("--seed",type=int,default=7); a=ap.parse_args()
    if a.draws<50 or a.tune<50: raise SystemExit("draws/tune must be >= 50")
    r=run(json.loads(a.dataset.read_text(encoding="utf-8")),a.draws,a.tune,a.seed); a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"status":r.get("status"),"sport":r.get("sport"),"fold_count":len(r.get("folds",[])),"logloss_mean":r.get("aggregate",{}).get("logloss_mean"),"logloss_worst":r.get("aggregate",{}).get("logloss_worst")},ensure_ascii=False,indent=2))
if __name__=="__main__": main()
