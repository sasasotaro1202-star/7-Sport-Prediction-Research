from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import arviz as az
import numpy as np
import pymc as pm
from src.research_policy import POLICY

MODEL_VERSION = "pymc-real-shadow-v1"

def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -40.0, 40.0)))

def logloss(y, p):
    p=np.clip(p,1e-7,1.0-1e-7)
    return float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p)))

def brier(y,p):
    return float(np.mean((p-y)**2))

def ece(y,p,bins=10):
    edges=np.linspace(0.0,1.0,bins+1); out=0.0
    for i in range(bins):
        mask=(p>=edges[i]) & ((p<edges[i+1]) if i<bins-1 else (p<=edges[i+1]))
        if mask.any():
            out += float(mask.mean())*abs(float(y[mask].mean())-float(p[mask].mean()))
    return out

def fit_logistic_baseline(x,y,l2=1.0,steps=60):
    x=np.asarray(x,float); y=np.asarray(y,float)
    xb=np.concatenate([np.ones((len(x),1)),x],axis=1)
    w=np.zeros(xb.shape[1],dtype=float)
    reg=np.eye(xb.shape[1],dtype=float)*float(l2)
    reg[0,0]=0.0
    for _ in range(int(steps)):
        p=sigmoid(xb@w)
        weight=np.clip(p*(1.0-p),1e-6,None)
        h=(xb.T*weight)@xb + reg
        g=xb.T@(p-y) + reg@w
        try:
            delta=np.linalg.solve(h,g)
        except np.linalg.LinAlgError:
            delta=np.linalg.pinv(h)@g
        w -= delta
        if float(np.max(np.abs(delta))) < 1e-7:
            break
    return w

def logistic_predict(w,x):
    xb=np.concatenate([np.ones((len(x),1)),np.asarray(x,float)],axis=1)
    return sigmoid(xb@w)

def prepare(dataset):
    if dataset.get("status")!="READY":
        raise ValueError(f"dataset not READY: {dataset.get('status')}")
    if dataset.get("dataset_scope")!="SPORT_SINGLE":
        raise ValueError("sport-isolated dataset required")
    rows=sorted(dataset.get("rows") or [],key=lambda r:(r["event_time_utc"],r["event_id"]))
    if len(rows)<100: raise ValueError("insufficient rows")
    split=int(len(rows)*0.8)
    train_rows = rows[:split]
    teams=sorted({str(r["team_a"]) for r in train_rows}|{str(r["team_b"]) for r in train_rows})
    oov_team="__OOV_TEAM__"
    teams.append(oov_team)
    ti={t:i for i,t in enumerate(teams)}
    ta=[];tb=[];y=[];x=[];m=[]
    sport = dataset["active_sports"][0]
    stats = tuple(POLICY[sport])
    if not stats:
        raise ValueError(f"no shadow stats configured for sport: {sport}")
    for r in rows:
        f=r.get("features") or {}; vals=[]; flags=[]
        for s in stats:
            a=f.get(f"A__{s}__mean"); b=f.get(f"B__{s}__mean")
            if a is None or b is None: vals.append(np.nan); flags.append(1.0)
            else: vals.append(float(a)-float(b)); flags.append(0.0)
        x.append(vals)
        m.append(flags)
        ta.append(ti.get(str(r["team_a"]), ti[oov_team]))
        tb.append(ti.get(str(r["team_b"]), ti[oov_team]))
        y.append(1 if r["outcome"]=="A" else 0)
    x=np.asarray(x,float); m=np.asarray(m,float)
    med=np.nanmedian(x[:split],axis=0); med=np.where(np.isfinite(med),med,0.0)
    x=np.where(np.isfinite(x),x,med)
    mu=x[:split].mean(axis=0); scale=x[:split].std(axis=0); scale=np.where(scale>1e-8,scale,1.0)
    x=(x-mu)/scale
    return rows,split,teams,np.asarray(ta,np.int64),np.asarray(tb,np.int64),np.concatenate([x,m],axis=1),np.asarray(y,np.int64)

def fit(dataset,seed=7):
    rows,split,teams,ta,tb,design,y=prepare(dataset)
    with pm.Model(coords={"team":np.arange(len(teams)),"feature":np.arange(design.shape[1])}):
        a=pm.Data("team_a",ta[:split]); b=pm.Data("team_b",tb[:split]); z=pm.Data("x",design[:split])
        sigma=pm.HalfNormal("sigma_strength",sigma=1.0)
        strength=pm.Normal("team_strength",mu=0.0,sigma=sigma,dims="team")
        intercept=pm.Normal("intercept",mu=0.0,sigma=1.0)
        beta=pm.Normal("beta",mu=0.0,sigma=1.0,dims="feature")
        centered_strength = strength - pm.math.mean(strength)
        logits=intercept+centered_strength[a]-centered_strength[b]+pm.math.sum(z*beta,axis=1)
        pm.Bernoulli("outcome",p=pm.math.sigmoid(logits),observed=y[:split])
        idata=pm.sample(draws=400,tune=400,chains=2,cores=2,random_seed=seed,target_accept=0.9,progressbar=False,return_inferencedata=True)
    post=idata.posterior
    isamp=np.asarray(post["intercept"].values); bsamp=np.asarray(post["beta"].values); tsamp=np.asarray(post["team_strength"].values)
    centered_tsamp = tsamp - tsamp.mean(axis=-1, keepdims=True)
    logits=(isamp[...,None]+centered_tsamp[...,ta[split:]]-centered_tsamp[...,tb[split:]]+np.einsum("scf,nf->scn",bsamp,design[split:]))
    p=sigmoid(logits).mean(axis=(0,1)); yt=y[split:]
    baseline_w=fit_logistic_baseline(design[:split],y[:split])
    p_logistic=logistic_predict(baseline_w,design[split:])
    stat_width=design.shape[1]//2
    swapped=design[split:].copy()
    swapped[:, :stat_width] *= -1.0
    swapped_logits=(isamp[...,None]+tsamp[...,tb[split:]]-tsamp[...,ta[split:]]+
                    np.einsum("scf,nf->scn",bsamp,swapped))
    p_swapped=sigmoid(swapped_logits).mean(axis=(0,1))
    symmetry_error=float(np.max(np.abs((p + p_swapped) - 1.0)))
    summary=az.summary(idata,var_names=["intercept","sigma_strength"],round_to=6)
    rhat=float(summary["r_hat"].max()); div=int(np.asarray(idata.sample_stats["diverging"]).sum())
    return {
      "status":"SHADOW_PERFORMANCE_OBSERVED","candidate":"pymc-devs/pymc","pymc_version":str(pm.__version__),
      "model_version":MODEL_VERSION,"seed":seed,"sport":dataset["active_sports"][0],
      "github_head_sha":os.environ.get("GITHUB_SHA"),
      "production_dependency":False,"automatic_promotion":False,
      "data":{"dataset_sha256":dataset.get("dataset_sha256"),"rows":len(rows),"train_rows":split,"test_rows":len(yt),"train_known_teams":len(teams)-1,
              "oov_team_bucket":True,
              "chronological_split":True,"event_cluster_one_case":True,"prediction_cutoff_before_outcome":True},
      "metrics":{"logloss":logloss(yt,p),"brier":brier(yt,p),"accuracy":float(np.mean((p>=0.5)==yt)),"ece":ece(yt,p),
                 "baseline_0_5_logloss":logloss(yt,np.full(len(yt),0.5)),"baseline_0_5_brier":brier(yt,np.full(len(yt),0.5)),
                 "matched_feature_logistic_logloss":logloss(yt,p_logistic),
                 "matched_feature_logistic_brier":brier(yt,p_logistic),
                 "matched_feature_logistic_accuracy":float(np.mean((p_logistic>=0.5)==yt)),
                 "matched_feature_logistic_ece":ece(yt,p_logistic),
                 "pymc_vs_matched_logistic_logloss_delta":float(logloss(yt,p_logistic)-logloss(yt,p))},
      "diagnostics":{"max_r_hat":rhat,"divergences":div,"finite_probabilities":bool(np.isfinite(p).all()),
                      "minimum_rhat_margin_to_fail":float(1.05-rhat),
                      "symmetry_max_abs_error":symmetry_error,
                      "symmetry_contract":"P(A)+P(B)=1 under exact A/B feature and team swap"},
      "evidence_boundary":{"real_7_sport_data_used":True,"performance_verification":False,"production_dependency":False,"automatic_promotion":False,
                           "promotion_status":"HOLD","required_next_gates":["incumbent/challenger WFO","calibration","ablation","robustness","frozen holdout","shadow comparison"]}
    }

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--dataset",type=Path,required=True); ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args(); d=json.loads(a.dataset.read_text(encoding="utf-8")); r=fit(d); a.output.parent.mkdir(parents=True,exist_ok=True)
    if r["diagnostics"]["max_r_hat"]>1.05: raise ValueError("PYMC_RHAT_FAIL")
    if r["diagnostics"]["divergences"]>0: raise ValueError("PYMC_DIVERGENCE_FAIL")
    if r["diagnostics"]["symmetry_max_abs_error"] > 1e-5: raise ValueError("PYMC_SYMMETRY_FAIL")
    a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps(r,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
