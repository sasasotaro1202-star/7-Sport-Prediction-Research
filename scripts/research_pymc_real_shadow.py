from __future__ import annotations

import argparse
import json
from pathlib import Path

import arviz as az
import numpy as np
import pymc as pm

MODEL_VERSION = "pymc-real-shadow-v1"
FEATURE_STATS = (
    "points", "rebounds", "assists", "steals", "blocks",
    "turnovers", "fieldGoalPct", "threePointPct", "freeThrowPct",
)

def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -40.0, 40.0)))

def logloss(y, p):
    p = np.clip(p, 1e-7, 1.0 - 1e-7)
    return float(-np.mean(y*np.log(p) + (1-y)*np.log1p(-p)))

def brier(y, p):
    return float(np.mean((p-y)**2))

def ece(y, p, bins=10):
    edges=np.linspace(0.0,1.0,bins+1)
    out=0.0
    for i in range(bins):
        mask=(p>=edges[i]) & ((p<edges[i+1]) if i<bins-1 else (p<=edges[i+1]))
        if mask.any():
            out += float(mask.mean())*abs(float(y[mask].mean())-float(p[mask].mean()))
    return out

def prepare(dataset):
    if dataset.get("status") != "READY":
        raise ValueError(f"dataset is not READY: {dataset.get('status')}")
    if dataset.get("dataset_scope") != "SPORT_SINGLE":
        raise ValueError("sport-isolated dataset required")
    rows=sorted(dataset.get("rows") or [], key=lambda r:(r["event_time_utc"],r["event_id"]))
    if len(rows)<100:
        raise ValueError(f"insufficient rows: {len(rows)}")
    split=int(len(rows)*0.8)
    if split<80 or len(rows)-split<20:
        raise ValueError("chronological split too small")
    teams=sorted({str(r["team_a"]) for r in rows}|{str(r["team_b"]) for r in rows})
    ti={t:i for i,t in enumerate(teams)}
    matrix=[]; miss=[]; ta=[]; tb=[]; y=[]
    for row in rows:
        feats=row.get("features") or {}
        vals=[]; flags=[]
        for stat in FEATURE_STATS:
            av=feats.get(f"A__{stat}__mean")
            bv=feats.get(f"B__{stat}__mean")
            if av is None or bv is None:
                vals.append(np.nan); flags.append(1.0)
            else:
                vals.append(float(av)-float(bv)); flags.append(0.0)
        matrix.append(vals); miss.append(flags)
        ta.append(ti[str(row["team_a"])]); tb.append(ti[str(row["team_b"])])
        y.append(1 if row["outcome"]=="A" else 0)
    x=np.asarray(matrix,dtype=float); missing=np.asarray(miss,dtype=float)
    train=x[:split]
    med=np.nanmedian(train,axis=0); med=np.where(np.isfinite(med),med,0.0)
    x=np.where(np.isfinite(x),x,med)
    mu=x[:split].mean(axis=0); scale=x[:split].std(axis=0); scale=np.where(scale>1e-8,scale,1.0)
    x=(x-mu)/scale
    design=np.concatenate([x,missing],axis=1)
    return rows,split,teams,np.asarray(ta,dtype=np.int64),np.asarray(tb,dtype=np.int64),design,np.asarray(y,dtype=np.int64)

def fit(dataset, seed=7):
    rows,split,teams,ta,tb,design,y=prepare(dataset)
    with pm.Model(coords={"team":np.arange(len(teams)),"feature":np.arange(design.shape[1])}) as model:
        a=pm.Data("team_a",ta[:split])
        b=pm.Data("team_b",tb[:split])
        x=pm.Data("x",design[:split])
        sigma=pm.HalfNormal("sigma_strength",sigma=1.0)
        strength=pm.Normal("team_strength",mu=0.0,sigma=sigma,dims="team")
        intercept=pm.Normal("intercept",mu=0.0,sigma=1.0)
        beta=pm.Normal("beta",mu=0.0,sigma=1.0,dims="feature")
        logit=intercept+strength[a]-strength[b]+pm.math.sum(x*beta,axis=1)
        pm.Bernoulli("outcome",p=pm.math.sigmoid(logit),observed=y[:split])
        idata=pm.sample(
            draws=400,tune=400,chains=2,cores=2,random_seed=seed,
            target_accept=0.9,progressbar=False,return_inferencedata=True,
        )
    post=idata.posterior
    intercept_s=np.asarray(post["intercept"].values)
    beta_s=np.asarray(post["beta"].values)
    team_s=np.asarray(post["team_strength"].values)
    test_x=design[split:]; test_a=ta[split:]; test_b=tb[split:]
    logits=(
        intercept_s[...,None]
        + team_s[...,test_a]-team_s[...,test_b]
        + np.einsum("scf,nf->scn",beta_s,test_x)
    )
    prob=sigmoid(logits).mean(axis=(0,1)); y_test=y[split:]
    summary=az.summary(idata,var_names=["intercept","sigma_strength"],round_to=6)
    max_rhat=float(summary["r_hat"].max())
    divergences=int(np.asarray(idata.sample_stats["diverging"]).sum())
    result={
        "status":"SHADOW_PERFORMANCE_OBSERVED",
        "candidate":"pymc-devs/pymc",
        "pymc_version":str(pm.__version__),
        "model_version":MODEL_VERSION,
        "seed":seed,
        "sport":dataset["active_sports"][0],
        "data":{
            "dataset_sha256":dataset.get("dataset_sha256"),
            "rows":len(rows),"train_rows":split,"test_rows":len(y_test),
            "unique_teams":len(teams),"chronological_split":True,
            "event_cluster_one_case":True,"prediction_cutoff_before_outcome":True,
        },
        "features":{
            "stats":list(FEATURE_STATS),
            "missing_indicators_included":True,
            "fit_scaler_on_train_only":True,
        },
        "metrics":{
            "logloss":logloss(y_test,prob),
            "brier":brier(y_test,prob),
            "accuracy":float(np.mean((prob>=0.5)==y_test)),
            "ece":ece(y_test,prob),
            "baseline_0_5_logloss":logloss(y_test,np.full(len(y_test),0.5)),
            "baseline_0_5_brier":brier(y_test,np.full(len(y_test),0.5)),
        },
        "diagnostics":{
            "max_r_hat":max_rhat,"divergences":divergences,
            "finite_probabilities":bool(np.isfinite(prob).all()),
            "posterior_samples_finite":bool(np.isfinite(intercept_s).all() and np.isfinite(beta_s).all() and np.isfinite(team_s).all()),
        },
        "evidence_boundary":{
            "real_7_sport_data_used":True,
            "performance_verification":False,
            "production_dependency":False,
            "automatic_promotion":False,
            "promotion_status":"HOLD",
            "required_next_gates":[
                "incumbent/challenger chronological WFO comparison",
                "calibration","ablation","robustness","frozen holdout","shadow comparison",
            ],
        },
    }
    if max_rhat>1.05:
        raise ValueError(f"PYMC_RHAT_FAIL:{max_rhat:.6f}")
    if divergences>0:
        raise ValueError(f"PYMC_DIVERGENCE_FAIL:{divergences}")
    if not result["diagnostics"]["finite_probabilities"]:
        raise ValueError("PYMC_NONFINITE_PROBABILITIES")
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--seed",type=int,default=7)
    args=parser.parse_args()
    data=json.loads(args.dataset.read_text(encoding="utf-8"))
    result=fit(data,args.seed)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":
    raise SystemExit(main())
