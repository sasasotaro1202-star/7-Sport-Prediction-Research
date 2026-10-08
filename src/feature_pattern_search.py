from __future__ import annotations

"""Chronological feature-family search.

The selector searches meaningful feature-family patterns rather than arbitrary
subsets. It uses a bounded score-guided beam over chronological inner-OOS blocks,
requires minimum coverage for optional families, and reserves the later
pre-holdout OOS region for an untouched main evaluation.
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


def _candidate_patterns(fams: Dict[str,List[str]], beam_width: int = 3, max_depth: int = 3):
    """Generate bounded family-pattern candidates; score-guided pruning happens in select_feature_pattern."""
    available=set(fams)
    core=[f for f in ("rating","form","workload","opponent") if f in available]
    if not core:
        core=[min(available)] if available else []
    extras=[f for f in (
        "h2h","stats","participant_profile","competition","event_context","interaction","core_other"
    ) if f in available]
    initial=[]
    if core:
        initial.append(tuple(core))
        for f in extras:
            initial.append(tuple(dict.fromkeys(core+[f])))
    else:
        initial=[(f,) for f in extras[:max(1,beam_width)]]
    all_f=tuple(sorted(available))
    if all_f and all_f not in initial:
        initial.append(all_f)
    return initial, extras


def select_feature_pattern(X, y, names, sport, min_rows=None):
    X=np.asarray(X,dtype=float)
    y=np.asarray(y,dtype=int)
    names=list(map(str,names))
    policy=_policy().get("search",{})
    min_rows=int(min_rows or policy.get("min_inner_rows",240))
    n=len(y)
    if X.ndim!=2 or X.shape[0]!=n or X.shape[1]!=len(names):
        return {"status":"BLOCKED","reason":"feature_matrix_schema_mismatch"}
    inner_fraction=float(policy.get("inner_fraction_end",.50))
    search_end=int(n*inner_fraction)
    if search_end < min_rows:
        return {
            "status":"FALLBACK_ALL_FEATURES",
            "reason":"insufficient_inner_rows",
            "selected_feature_names":names,
            "selected_feature_count":len(names),
            "search_data_max_index":max(-1,search_end-1),
            "main_oos_reserved_from_index":search_end,
            "holdout_access":False,
            "main_oos_access":False,
        }
    y_search=y[:search_end]
    if len(np.unique(y_search))<2:
        return {
            "status":"FALLBACK_ALL_FEATURES",
            "reason":"inner_search_single_class",
            "selected_feature_names":names,
            "selected_feature_count":len(names),
            "search_data_max_index":search_end-1,
            "main_oos_reserved_from_index":search_end,
            "holdout_access":False,
            "main_oos_access":False,
        }
    fams=_families(names)
    beam_width=max(1,int(policy.get("beam_width",3)))
    max_depth=max(1,int(policy.get("max_depth",3)))
    min_family_coverage=float(policy.get("min_family_coverage",0.10))
    initial,extras=_candidate_patterns(fams,beam_width,max_depth)
    search_matrix=X[:search_end]
    starts_edges=np.linspace(max(60,int(search_end*.40)),search_end,4,dtype=int)
    starts=[int(starts_edges[i]) for i in range(3)]
    ends=[int(starts_edges[i+1]) for i in range(3)]

    def score(pattern):
        idx=[i for i,name in enumerate(names) if feature_family(name) in pattern]
        if not idx:
            return None
        family_coverage={}
        for fam in pattern:
            fidx=[i for i,name in enumerate(names) if feature_family(name)==fam]
            if not fidx:
                continue
            family_coverage[fam]=float(np.isfinite(search_matrix[:,fidx]).any(axis=1).mean())
        optional=[f for f in pattern if f in extras]
        sparse=[f for f in optional if family_coverage.get(f,0.0) < min_family_coverage]
        if sparse:
            return None
        result=_score_pattern(X,y,idx,starts,ends)
        if result is None:
            return None
        return {
            **result,
            "pattern":list(pattern),
            "feature_count":len(idx),
            "feature_names":[names[i] for i in idx],
            "family_coverage":family_coverage,
        }

    scored_by_key={}
    beam=[]
    for pattern in initial:
        key=tuple(pattern)
        if key in scored_by_key:
            continue
        z=score(pattern)
        if z is not None:
            scored_by_key[key]=z
    ranked_initial=sorted(
        scored_by_key.values(),
        key=lambda z:(z["objective"],z["mean_logloss"],z["mean_brier"],z["feature_count"],json.dumps(z["pattern"],sort_keys=True))
    )
    beam=[tuple(z["pattern"]) for z in ranked_initial[:beam_width]]

    for depth in range(2,max_depth+1):
        candidates=[]
        seen=set(scored_by_key)
        for p in beam:
            for f in extras:
                if f in p:
                    continue
                q=tuple(dict.fromkeys(p+(f,)))
                if q in seen:
                    continue
                seen.add(q)
                candidates.append(q)
        scored_new=[]
        for pattern in candidates:
            z=score(pattern)
            if z is not None:
                scored_by_key[tuple(pattern)]=z
                scored_new.append(z)
        ranked_depth=sorted(
            scored_new,
            key=lambda z:(z["objective"],z["mean_logloss"],z["mean_brier"],z["feature_count"],json.dumps(z["pattern"],sort_keys=True))
        )
        beam=[tuple(z["pattern"]) for z in ranked_depth[:beam_width]]
        if not beam:
            break

    all_f=tuple(sorted(fams))
    if all_f not in scored_by_key and set(all_f).issubset(set(fams)):
        z=score(all_f)
        if z is not None:
            scored_by_key[all_f]=z

    scored=list(scored_by_key.values())
    if not scored:
        return {
            "status":"FALLBACK_ALL_FEATURES",
            "reason":"no_valid_inner_oos_pattern",
            "selected_feature_names":names,
            "selected_feature_count":len(names),
            "search_data_max_index":search_end-1,
            "main_oos_reserved_from_index":search_end,
            "holdout_access":False,
            "main_oos_access":False,
            "family_map":{k:len(v) for k,v in fams.items()},
        }
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
        "search_strategy":"chronological_inner_oos_score_guided_beam",
        "search_data_max_index":search_end-1,
        "main_oos_reserved_from_index":search_end,
        "holdout_access":False,
        "main_oos_access":False,
        "beam_width":beam_width,
        "max_depth":max_depth,
        "min_family_coverage":min_family_coverage,
        "family_map":{k:len(v) for k,v in fams.items()},
        "policy_version":"participant-context-pattern-selection-v2",
    }
