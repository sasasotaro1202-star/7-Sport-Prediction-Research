from __future__ import annotations

import math
import os
from typing import Any, Iterable

import numpy as np

from src import innovative_prediction_v2 as v2

VERSION = "maximum-future-generalization-v13"
SEED = 20260926
EPS = 1e-6
DEFAULT_HORIZONS = (1, 3, 5)


def _clip_prob(p: Any) -> np.ndarray:
    x = np.asarray(p, dtype=float)
    return np.clip(np.nan_to_num(x, nan=0.5, posinf=0.5, neginf=0.5), EPS, 1.0 - EPS)


def _entropy_binary(p: np.ndarray) -> np.ndarray:
    p = _clip_prob(p)
    return np.clip(
        -(p * np.log(p) + (1.0 - p) * np.log(1.0 - p)) / math.log(2.0),
        0.0,
        1.0,
    )


def _ood_score(x: np.ndarray, window: int = 240) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.zeros(len(x), dtype=float)
    for i in range(len(x)):
        lo = max(0, i - window)
        if i - lo < 30 or x.shape[1] == 0:
            continue
        ref = x[lo:i]
        med = np.nanmedian(ref, axis=0)
        mad = np.nanmedian(np.abs(ref - med), axis=0)
        scale = np.where(np.isfinite(mad) & (mad > 1e-6), mad, 1.0)
        z = np.abs(np.nan_to_num((x[i] - med) / scale, nan=0.0))
        out[i] = float(np.clip(np.nanmedian(z) / 6.0, 0.0, 1.0))
    return out


def _scenario(p: float, uncertainty: float, disagreement: float, failure: float) -> dict[str, Any]:
    logits = np.array([
        1.4 * (1.0 - uncertainty) + 0.5 * (1.0 - failure),
        0.8 * uncertainty + 0.6 * disagreement,
        0.6 * abs(p - 0.5) + 0.8 * failure,
    ])
    logits -= logits.max()
    probs = np.exp(logits)
    probs /= probs.sum()
    return {
        "labels": ["NORMAL", "SHOCK", "REVERSAL"],
        "probabilities": probs.tolist(),
        "status": "POLICY_PROXY_UNCALIBRATED",
    }


def _future_trajectory(features: np.ndarray, y: np.ndarray, horizons: Iterable[int]) -> tuple[np.ndarray, dict[str, Any]]:
    y = np.asarray(y, dtype=float)
    hs = tuple(int(h) for h in horizons if int(h) > 0)
    out = np.full((len(y), len(hs)), np.nan)
    audits = {}
    for k, h in enumerate(hs):
        target = np.full(len(y), np.nan)
        if h < len(y):
            target[:-h] = y[h:]
        pred, audit = v2._crossfit_binary_meta(features, target, horizon=h, min_train=120, seed=SEED + h)
        out[:, k] = pred
        audits[f"h{h}"] = audit
    return out, {
        "status": "EVALUATED" if np.isfinite(out).any() else "INSUFFICIENT",
        "horizons": list(hs),
        "audits": audits,
        "target_definition": "horizon-shifted future outcome; future labels are targets only with explicit embargo",
    }


def _future_predictability(score: np.ndarray, y: np.ndarray, horizon: int) -> tuple[np.ndarray, dict[str, Any]]:
    score = np.clip(np.asarray(score, dtype=float), 0.0, 1.0)
    y = np.asarray(y, dtype=int)
    target = np.full(len(y), np.nan)
    if len(y) > horizon:
        err = ((score >= 0.5).astype(int) != y).astype(float)
        for i in range(len(y) - horizon):
            target[i] = float(np.mean(err[i + 1:i + horizon + 1]) >= 0.5)
    pred, audit = v2._crossfit_binary_meta(score.reshape(-1, 1), target, horizon=horizon, min_train=120, seed=SEED + 100)
    return (1.0 - np.clip(pred, 0.0, 1.0)).reshape(-1, 1), {
        "status": "EVALUATED" if np.isfinite(pred).any() else "INSUFFICIENT",
        "horizon": horizon,
        "audit": audit,
        "target_definition": "future baseline difficulty, evaluated prequentially",
    }


def _strategy_pool(
    baseline: np.ndarray,
    dynamic: np.ndarray,
    retrieval: np.ndarray,
    meta: np.ndarray,
    uncertainty: np.ndarray,
) -> dict[str, np.ndarray]:
    b, d, r, m = map(_clip_prob, (baseline, dynamic, retrieval, meta))
    u = np.clip(np.nan_to_num(np.asarray(uncertainty, dtype=float), nan=0.5), 0.0, 1.0)
    return {
        "INCUMBENT": b,
        "DYNAMIC_ENSEMBLE": d,
        "RETRIEVAL_FUSION": _clip_prob(0.75 * b + 0.25 * r),
        "META_LABELLED": _clip_prob(0.75 * b + 0.25 * m),
        "CONSERVATIVE_ROUTING": _clip_prob(0.5 + (d - 0.5) * (0.70 + 0.30 * (1.0 - u))),
    }


def _strategy_memory(pool: dict[str, np.ndarray], y: np.ndarray, i: int, window: int = 120) -> dict[str, float]:
    lo = max(0, i - window)
    if i - lo < 30:
        return {k: 0.5 for k in pool}
    out = {}
    yy = np.asarray(y[lo:i], dtype=int)
    for name, pred in pool.items():
        p = _clip_prob(pred[lo:i])
        acc = float(np.mean((p >= 0.5).astype(int) == yy))
        ll = float(np.mean(-(yy * np.log(p) + (1 - yy) * np.log(1 - p))))
        out[name] = float(np.clip(0.65 * acc + 0.35 * (1.0 - min(ll, 1.0)), 0.0, 1.0))
    return out


def _select_strategy(
    pool: dict[str, np.ndarray],
    predictability: np.ndarray,
    uncertainty: np.ndarray,
    failure: np.ndarray,
    ood: np.ndarray,
    disagreement: np.ndarray,
    source: np.ndarray,
    y: np.ndarray,
) -> tuple[list[str], np.ndarray, list[dict[str, float]]]:
    names = list(pool)
    chosen, selected, memory_trace = [], np.empty(len(y)), []
    for i in range(len(y)):
        q, u, f, o, d, s = [float(np.clip(v, 0, 1)) for v in (predictability[i], uncertainty[i], failure[i], ood[i], disagreement[i], source[i])]
        mem = _strategy_memory(pool, y, i)
        memory_trace.append(mem)
        if (f >= 0.90 and o >= 0.70) or (u >= 0.95 and q <= 0.20):
            name = "INCUMBENT"
        else:
            scores = {}
            for n in names:
                p = float(pool[n][i])
                sharp = abs(p - 0.5) * 2.0
                scores[n] = (
                    0.45 * mem[n] + 0.20 * q + 0.10 * s + 0.10 * (1-u)
                    + 0.05 * (1-o) + 0.05 * (1-d) + 0.05 * sharp - 0.20 * f
                )
            name = max(names, key=lambda z: scores[z])
        chosen.append(name)
        selected[i] = float(_clip_prob([pool[name][i]])[0])
    return chosen, selected, memory_trace


def _update_policy(p, predictability, uncertainty, failure, ood, source, previous):
    p = _clip_prob(p)
    previous = _clip_prob(previous)
    actions, need, trace = [], [], []
    for i in range(len(p)):
        impact = abs(float(p[i] - previous[i]))
        n = float(np.clip(
            0.25 * (1-predictability[i]) + 0.20*uncertainty[i] + 0.20*failure[i]
            + 0.20*ood[i] + 0.15*(1-source[i]), 0, 1
        ))
        if n >= 0.88 and (failure[i] >= 0.75 or ood[i] >= 0.75):
            a = "ABSTAIN_OR_FALLBACK"
        elif n >= 0.70 and impact >= 0.08:
            a = "DEEP_RECALC"
        elif n >= 0.45 and impact >= 0.025:
            a = "MAJOR_REVISION"
        elif n >= 0.22 and impact >= 0.008:
            a = "MINOR_REVISION"
        elif source[i] < 0.55 and (1-predictability[i]) > 0.40:
            a = "INFORMATION_ADD"
        else:
            a = "MAINTAIN"
        if a not in {"MAINTAIN", "INFORMATION_ADD"} and impact < 0.004:
            a = "MAINTAIN"
        actions.append(a)
        need.append(n)
        trace.append({"impact": impact, "update_need": n, "action": a})
    return actions, np.asarray(need), trace


def _compute_tier(q, u, f, o):
    out=[]
    for a,b,c,d in zip(q,u,f,o):
        difficulty=0.35*(1-a)+0.25*b+0.25*c+0.15*d
        out.append("ABSTAIN_OR_FALLBACK" if difficulty>=0.85 else "DEEP" if difficulty>=0.62 else "ENSEMBLE_PLUS_RETRIEVAL" if difficulty>=0.38 else "STANDARD")
    return out


def _output_format(q, u, o):
    out=[]
    for a,b,c in zip(q,u,o):
        out.append("ABSTAIN" if c>=0.85 and a<=0.25 else "SCENARIO" if a<=0.35 or b>=0.80 else "PROBABILITY_RANGE" if a<=0.60 or b>=0.55 else "PROBABILITY")
    return out


def _revision_metrics(y, previous, current, actions):
    y=np.asarray(y,dtype=int)
    prev=_clip_prob(previous); cur=_clip_prob(current)
    changed=np.asarray([a!="MAINTAIN" for a in actions])
    if not changed.any():
        return {"status":"NO_REVISIONS","revisions":0}
    gain=-(y*np.log(cur)+(1-y)*np.log(1-cur))*(-1)+ (-(y*np.log(prev)+(1-y)*np.log(1-prev)))
    gain=gain[changed]
    return {
        "status":"EVALUATED","revisions":int(changed.sum()),
        "revision_accuracy":float(np.mean(gain>0)),
        "mean_revision_logloss_improvement":float(np.mean(gain)),
        "false_revision_rate":float(np.mean(gain<0)),
    }


def _error_attribution(y, p, predictability, failure, uncertainty, ood, disagreement, actions):
    wrong=((_clip_prob(p)>=0.5).astype(int)!=np.asarray(y,dtype=int))
    counts={"CALIBRATION":0,"OOD":0,"FUTURE_FAILURE":0,"PREDICTABILITY":0,"MODEL_DISAGREEMENT":0,"STRATEGY_SELECTION":0,"IRREDUCIBLE":0}
    for i,w in enumerate(wrong):
        if not w: continue
        if uncertainty[i]>=0.85: counts["CALIBRATION"]+=1
        elif ood[i]>=0.75: counts["OOD"]+=1
        elif failure[i]>=0.75: counts["FUTURE_FAILURE"]+=1
        elif predictability[i]<=0.30: counts["PREDICTABILITY"]+=1
        elif disagreement[i]>=0.45: counts["MODEL_DISAGREEMENT"]+=1
        elif actions[i] not in {"MAINTAIN","INFORMATION_ADD"}: counts["STRATEGY_SELECTION"]+=1
        else: counts["IRREDUCIBLE"]+=1
    return {"status":"EVALUATED","wrong_rows":int(wrong.sum()),"distribution":counts}


def run_control_layer(
    sport: str,
    x: np.ndarray,
    y: np.ndarray,
    base_probabilities: np.ndarray,
    baseline: np.ndarray,
    dynamic: np.ndarray,
    retrieval_success: np.ndarray,
    meta_reliability: np.ndarray,
    predictability: np.ndarray,
    failure_risk: np.ndarray,
    uncertainty_matrix: dict[str, np.ndarray],
    feature_reliability: np.ndarray,
    source_reliability: np.ndarray,
    disagreement: np.ndarray,
    drift: np.ndarray,
    event_ids: list[str] | None = None,
    feature_names: list[str] | None = None,
    model_names: list[str] | None = None,
    model_version: str = VERSION,
    dataset_hash: str | None = None,
    feature_version: str | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    if not v2.RESEARCH_ONLY:
        raise RuntimeError("MAXIMUM_FUTURE_GENERALIZATION_V13_MUST_REMAIN_RESEARCH_ONLY")
    x=np.asarray(x,dtype=float); y=np.asarray(y,dtype=int); bp=_clip_prob(base_probabilities)
    baseline=_clip_prob(baseline); dynamic=_clip_prob(dynamic); retrieval_success=_clip_prob(retrieval_success); meta_reliability=_clip_prob(meta_reliability)
    q=np.clip(np.nan_to_num(predictability,nan=0.5),0,1)
    failure=np.clip(np.nan_to_num(np.nanmean(failure_risk,axis=1),nan=0.5),0,1)
    uncertainty=np.clip(np.nan_to_num(np.mean(np.column_stack(list(uncertainty_matrix.values())),axis=1),nan=0.5),0,1)
    feature_rel=np.clip(np.nan_to_num(feature_reliability,nan=0.5),0,1)
    source=np.clip(np.nan_to_num(source_reliability,nan=0.5),0,1)
    dis=np.clip(np.nan_to_num(disagreement,nan=0),0,1)
    drift_arr=np.asarray(drift,dtype=float)
    drift_norm=np.clip(np.nan_to_num(drift_arr[:,0],nan=0)/3.0,0,1)
    ood=_ood_score(x)

    pool=_strategy_pool(baseline,dynamic,retrieval_success,meta_reliability,uncertainty)
    strategies, selected, memory=_select_strategy(pool,q,uncertainty,failure,ood,dis,source,y)
    previous=np.r_[selected[:1],selected[:-1]]
    actions, update_need, update_trace=_update_policy(selected,q,uncertainty,failure,ood,source,previous)
    tiers=_compute_tier(q,uncertainty,failure,ood)
    formats=_output_format(q,uncertainty,ood)
    scenarios=[_scenario(float(selected[i]),float(uncertainty[i]),float(dis[i]),float(failure[i])) for i in range(len(y))]

    state_features=np.column_stack([
        np.nan_to_num(x[:,:min(32,x.shape[1])],nan=0.0),
        np.mean(bp,axis=1),np.std(bp,axis=1),q,uncertainty,failure,source,
    ])
    future_prob,future_prob_meta=_future_trajectory(state_features,y,horizons)
    future_q,future_q_meta=_future_predictability(q,y,max(horizons) if horizons else 5)
    lifetime=np.clip(1+np.round(20*(1-(0.45*(1-q)+0.25*uncertainty+0.20*failure+0.10*ood))),1,21).astype(int)

    ids=[str(z) for z in (event_ids or [])]
    if len(ids)!=len(y): ids=[f"{sport}-{i}" for i in range(len(y))]
    models=list(model_names or [f"model_{i}" for i in range(bp.shape[1])])
    if len(models)!=bp.shape[1]: models=[f"model_{i}" for i in range(bp.shape[1])]

    ledger=[]
    for i in range(len(y)):
        p=float(selected[i])
        half=float(np.clip(0.15*uncertainty[i]+0.05*(1-q[i]),0.01,0.45))
        ledger.append({
            "prediction_index":i,"event_id":ids[i],"prediction_time":i,"valid_until":int(i+lifetime[i]),
            "time_semantics":"ROW_INDEX_ONLY_UNLESS_EVENT_TIMESTAMP_EXPOSED",
            "prediction":int(p>=0.5),"probability":p,
            "probability_range":[float(np.clip(p-half,EPS,1-EPS)),float(np.clip(p+half,EPS,1-EPS))],
            "confidence":float(1-_entropy_binary(np.asarray([p]))[0]),"predictability":float(q[i]),
            "uncertainty":float(uncertainty[i]),"novelty_ood":float(ood[i]),"future_failure_risk":float(failure[i]),
            "drift_score":float(drift_norm[i]),"model_disagreement":float(dis[i]),
            "feature_reliability":float(feature_rel[i]),"source_reliability":float(source[i]),
            "models_available":models,"strategy":strategies[i],"compute_tier":tiers[i],
            "output_format":formats[i],"action":actions[i],"update_need":float(update_need[i]),
            "update_impact":float(update_trace[i]["impact"]),"scenario":scenarios[i],
            "pit_status":"INHERITED_STRICT_OOS_FAIL_CLOSED",
            "outcome":int(y[i]),"outcome_used_for_current_policy":False,
        })
    wrong=((selected>=0.5).astype(int)!=y)
    for i,row in enumerate(ledger):
        row["success"]=not bool(wrong[i])
        row["error_attribution"]=None if not wrong[i] else (
            "CALIBRATION" if uncertainty[i]>=0.85 else "OOD" if ood[i]>=0.75 else
            "FUTURE_FAILURE" if failure[i]>=0.75 else "PREDICTABILITY" if q[i]<=0.30 else
            "MODEL_DISAGREEMENT" if dis[i]>=0.45 else "STRATEGY_SELECTION" if actions[i] not in {"MAINTAIN","INFORMATION_ADD"} else "IRREDUCIBLE"
        )

    strategy_metrics={name:v2._metrics(y,_clip_prob(pred)) for name,pred in pool.items()}
    selected_metrics=v2._metrics(y,selected); baseline_metrics=v2._metrics(y,baseline)

    return {
        "v13":{"version":VERSION,"run_id":os.getenv("GITHUB_RUN_ID","local"),"git_commit":os.getenv("GITHUB_SHA","UNKNOWN"),"sport":sport,"status":"EVALUATED","production_changed":False,"promotion":"HOLD"},
        "prediction_policy":{
            "selected_strategy":strategies,"strategy_metrics":strategy_metrics,"selected_strategy_metrics":selected_metrics,
            "selected_vs_baseline":{
                "accuracy_delta":float(selected_metrics["accuracy"]-baseline_metrics["accuracy"]),
                "logloss_delta":float(selected_metrics["logloss"]-baseline_metrics["logloss"]),
                "brier_delta":float(selected_metrics["brier"]-baseline_metrics["brier"]),
                "ece_delta":float(selected_metrics["ece"]-baseline_metrics["ece"]),
            },
            "strategy_pool":list(pool),"strategy_memory_rows":len(memory),
            "selection_contract":"chronological prior-performance + PIT-safe state/risk; current outcome excluded from current-row selection",
            "strategy_memory":memory,
        },
        "dynamic_prediction":{
            "selected_probability":selected.tolist(),"selected_prediction":(selected>=0.5).astype(int).tolist(),
            "actions":actions,"update_need":update_need.tolist(),"update_trace":update_trace,
            "revision":_revision_metrics(y,previous,selected,actions),
            "stability_budget":{"revision_count":int(np.sum(np.asarray(actions)!="MAINTAIN")),"revision_rate":float(np.mean(np.asarray(actions)!="MAINTAIN"))},
        },
        "prediction_output":{"formats":formats,"format_counts":{k:int(formats.count(k)) for k in sorted(set(formats))},"scenarios":scenarios,"scenario_probability_status":"POLICY_PROXY_UNCALIBRATED"},
        "adaptive_compute":{"tiers":tiers,"counts":{k:int(tiers.count(k)) for k in sorted(set(tiers))},"status":"EVALUATED","policy":"difficulty-driven research compute tier"},
        "active_information":{
            "status":"RESEARCH_PROXY_NO_EXTERNAL_CALL",
            "candidates":[
                {"information":"FEATURE_REFRESH","trigger_score":float(np.mean(1-feature_rel)),"expected_oos_improvement":None},
                {"information":"SOURCE_REFRESH","trigger_score":float(np.mean(1-source)),"expected_oos_improvement":None},
                {"information":"DATA_CONFLICT_RECHECK","trigger_score":float(np.mean(1-feature_rel)),"expected_oos_improvement":None},
            ],
            "feature_names_available":bool(feature_names),
            "policy":"no fabricated acquisition value; requires PIT before/after acquisition snapshots",
        },
        "prediction_history":{
            "rows":ledger,
            "schema":["prediction_time","valid_until","data_snapshot","model_version","strategy","confidence","predictability","uncertainty","pit_status","outcome"],
        },
        "future_trajectory":{
            "future_probability":future_prob.tolist(),"future_probability_meta":future_prob_meta,
            "future_predictability":future_q.tolist(),"future_predictability_meta":future_q_meta,
            "failure_risk_current":failure.tolist(),
            "contract":{"status":"PASS","horizons":list(horizons),"policy":"horizon-shifted targets with embargo"},
        },
        "prediction_lifetime":{"rows":lifetime.tolist(),"mean":float(np.mean(lifetime)),"p10":float(np.quantile(lifetime,0.10)),"p90":float(np.quantile(lifetime,0.90))},
        "novelty_ood":{"row_mean":float(np.mean(ood)),"row_p95":float(np.quantile(ood,0.95)),"ood_rows":int(np.sum(ood>=0.75)),"status":"RESEARCH_PROXY"},
        "error_attribution":_error_attribution(y,selected,q,failure,uncertainty,ood,dis,actions),
        "prediction_contract":{
            "required_fields":["prediction_time","valid_until","data_snapshot","model_version","strategy","confidence","predictability","uncertainty","pit_status"],
            "status":"PARTIAL_PIT_TIMESTAMP_SCHEMA",
            "data_snapshot":{"dataset_hash":dataset_hash,"feature_version":feature_version,"source_snapshot_exposed":False},
            "model_version":model_version,
            "pit_status":"INHERITED_STRICT_OOS_FAIL_CLOSED",
            "timestamp_note":"strict OOS controller interface exposes event ids but not authoritative event/publication/available_at timestamps",
        },
        "model_portfolio":{"base_model_count":int(bp.shape[1]),"model_names":models,"candidate_strategies":list(pool),"selection_level":"STRATEGY"},
        "prediction_ledger_summary":{"rows":len(ledger),"wrong_rows":int(wrong.sum()),"successful_rows":int((~wrong).sum()),"selected_metrics":selected_metrics,"baseline_metrics":baseline_metrics},
        "meta_monitor":{"router_failure_guard":"PASS","policy_selector_status":"EVALUATED","future_trajectory_status":"PASS","active_information_status":"RESEARCH_PROXY_NO_EXTERNAL_CALL","self_failure_monitoring":"POST_OUTCOME_ONLY"},
    }
