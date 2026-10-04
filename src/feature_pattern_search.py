from __future__ import annotations

"""Chronological feature-family search.

The selector deliberately searches patterns, not arbitrary feature subsets. It
keeps the combinatorial problem bounded, uses only an early training prefix for
selection, and reserves the later pre-holdout OOS region for an untouched main
evaluation.
"""

import json
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "FEATURE_PATTERN_POLICY.json"


def _policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def feature_family(name: str) -> str:
    n=str(name)
    if "__profile__" in n:
        return "participant_profile"
    if "__h2h_" in n or n.startswith("D__h2h_"):
        return "h2h"
    if "__x_" in n or "_x_" in n:
        return "interaction"
    if "__elo" in n or "opponent_elo" in n:
        return "rating" if "opponent_elo" not in n else "opponent"
    if any(k in n for k in ("recent_winrate","recent_form","streak","recent_margin")):
        return "form"
    if any(k in n for k in ("rest_days","games_last_","short_rest")):
        return "workload"
    if n.startswith("competition_") or n.startswith("D__competition_"):
        return "competition"
    if "__event__" in n or n.startswith("D__event__"):
        return "event_context"
    if "opponent_elo" in n:
        return "opponent"
    if any(k in n for k in ("__sig_str__","__takedown__","__td_pct__","__sub_attempts__","__control_time__","__points__","__rebounds__","__assists__","__attack__","__serve__","__receive__","__block__","__rating__","__acs__","__adr__","__kast__","__k_d__","__fk_fd__","__ace__","__double_fault__","__first_serve__","__break_points_")):
        return "stats"
    if any(k in n for k in ("stat_coverage","stat_freshness","__age_days","__n")):
        return "stats"
    return "core_other"


def _families(names: Sequence[str]) -> Dict[str,List[str]]:
    out={}
    for name in names:
        out.setdefault(feature_family(name),[]).append(name)
    return {k:sorted(v) for k,v in out.items()}


def _probe_models():
    return {
        "hist_gradient_boosting_missing": Pipeline([
            ("i",SimpleImputer(strategy="median",add_indicator=True)),
            ("m",HistGradientBoostingClassifier(
                max_iter=160,learning_rate=.045,l2_regularization=2.0,
                max_leaf_nodes=15,random_state=20261004
            )),
        ]),
        "logistic": Pipeline([
            ("i",SimpleImputer(strategy="median",add_indicator=True)),
            ("s",StandardScaler()),
            ("m",LogisticRegression(C=.25,max_iter=2000,random_state=20261004)),
        ]),
    }


def _metric(y,p):
    y=np.asarray(y,dtype=int)
    p=np.clip(np.asarray(p,dtype=float),1e-6,1-1e-6)
    ll=float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
    br=float(np.mean((p-y)**2))
    return ll,br


def _score_pattern(X,y,feature_idx,starts,ends):
    if not feature_idx:
        return None
    fold_scores={m:[] for m in _probe_models()}
    for start,end in zip(starts,ends):
        tr_end=start
        te_start=start
        te_end=end
        if tr_end < 60 or te_end <= te_start:
            continue
        Xtr=X[:tr_end,feature_idx]
        ytr=y[:tr_end]
        Xte=X[te_start:te_end,feature_idx]
        yte=y[te_start:te_end]
        if len(np.unique(ytr))<2 or len(np.unique(yte))<2:
            continue
        for name,model in _probe_models().items():
            model.fit(Xtr,ytr)
            p=model.predict_proba(Xte)[:,1]
            fold_scores[name].append(_metric(yte,p))
    usable=[v for v in fold_scores.values() if len(v)>=2]
    if not usable:
        return None
    model_means=[]
    for vals in usable:
        ll=np.asarray([v[0] for v in vals],dtype=float)
        br=np.asarray([v[1] for v in vals],dtype=float)
        model_means.append({
            "mean_logloss":float(ll.mean()),
            "logloss_std":float(ll.std(ddof=1)) if len(ll)>1 else 0.0,
            "mean_brier":float(br.mean()),
            "worst_logloss":float(ll.max()),
        })
    mean_ll=float(np.mean([x["mean_logloss"] for x in model_means]))
    ll_std=float(np.mean([x["logloss_std"] for x in model_means]))
    mean_br=float(np.mean([x["mean_brier"] for x in model_means]))
    worst=float(np.max([x["worst_logloss"] for x in model_means]))
    robust=float(mean_ll + .20*ll_std + .10*mean_br + .05*max(0.0,worst-mean_ll))
    return {
        "objective":robust,
        "mean_logloss":mean_ll,
        "logloss_std":ll_std,
        "mean_brier":mean_br,
        "worst_logloss":worst,
        "folds":min(len(v) for v in usable),
    }


def _candidate_patterns(fams: Dict[str,List[str]]) -> List[Tuple[str,...]]:
    available=set(fams)
    core=[f for f in ("rating","form","workload","opponent") if f in available]
    if not core:
        core=[min(available)] if available else []
    patterns=[tuple(core)]
    extras=[f for f in (
        "h2h","stats","participant_profile","competition","event_context","interaction","core_other"
    ) if f in available]
    for f in extras:
        patterns.append(tuple(dict.fromkeys(core+[f])))
    frontier=list(patterns)
    beam=list(patterns[:1])
    seen=set(patterns)
    for _depth in range(2,4):
        scored_frontier=[]
        for p in beam:
            for f in extras:
                if f in p:
                    continue
                q=tuple(dict.fromkeys(p+(f,)))
                if q in seen:
                    continue
                seen.add(q)
                scored_frontier.append(q)
        frontier.extend(scored_frontier)
        beam=scored_frontier[:3]
    # Always include all available families as a final stress candidate.
    all_f=tuple(sorted(available))
    if all_f not in seen:
        frontier.append(all_f)
    return list(dict.fromkeys(frontier))


def select_feature_pattern(X, y, names, sport, min_rows=None):
    X=np.asarray(X,dtype=float)
    y=np.asarray(y,dtype=int)
    names=list(map(str,names))
    policy=_policy().get("search",{})
    min_rows=int(min_rows or policy.get("min_inner_rows",240))
    n=len(y)
    if X.ndim!=2 or X.shape[0]!=n or X.shape[1]!=len(names):
        return {"status":"BLOCKED","reason":"feature_matrix_schema_mismatch"}
    search_end=min(n-1,max(min_rows, int(n*float(policy.get("inner_fraction_end",.50)))))
    if search_end < min_rows:
        return {"status":"FALLBACK_ALL_FEATURES","reason":"insufficient_inner_rows","selected_feature_names":names,"search_data_max_index":max(-1,search_end),"main_oos_reserved_from_index":search_end+1}
    y_search=y[:search_end]
    if len(np.unique(y_search))<2:
        return {"status":"FALLBACK_ALL_FEATURES","reason":"inner_search_single_class","selected_feature_names":names,"search_data_max_index":search_end-1,"main_oos_reserved_from_index":search_end}
    fams=_families(names)
    patterns=_candidate_patterns(fams)
    # Three non-overlapping validation blocks entirely inside the first half.
    start0=max(60,int(search_end*.40))
    edges=np.linspace(start0,search_end,4,dtype=int)
    starts=[int(edges[i]) for i in range(3)]
    ends=[int(edges[i+1]) for i in range(3)]
    scored=[]
    for pattern in patterns:
        idx=[i for i,name in enumerate(names) if feature_family(name) in pattern]
        score=_score_pattern(X,y,idx,starts,ends)
        if score is None:
            continue
        scored.append({**score,"pattern":list(pattern),"feature_count":len(idx),"feature_names":[names[i] for i in idx]})
    if not scored:
        return {"status":"FALLBACK_ALL_FEATURES","reason":"no_valid_inner_oos_pattern","selected_feature_names":names,"search_data_max_index":search_end-1,"main_oos_reserved_from_index":search_end}
    scored.sort(key=lambda z:(z["objective"],z["mean_logloss"],z["mean_brier"],z["feature_count"],json.dumps(z["pattern"],sort_keys=True)))
    best=scored[0]
    return {
        "status":"SELECTED",
        "sport":sport,
        "selected_pattern":best["pattern"],
        "selected_feature_names":best["feature_names"],
        "selected_feature_count":best["feature_count"],
        "selected_objective":best["objective"],
        "candidate_patterns":scored,
        "search_strategy":"chronological_inner_oos_beam",
        "search_data_max_index":search_end-1,
        "main_oos_reserved_from_index":search_end,
        "holdout_access":False,
        "main_oos_access":False,
        "family_map":{k:len(v) for k,v in fams.items()},
        "policy_version":"participant-context-pattern-selection-v1",
    }
