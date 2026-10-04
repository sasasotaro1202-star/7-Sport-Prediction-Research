from __future__ import annotations

import math
import re
from itertools import combinations
from typing import Iterable

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FAMILY_ORDER = (
    "identity_strength",
    "form_load",
    "performance_history",
    "entity_profile",
    "team_roster_context",
    "competition_context",
    "matchday_intelligence",
    "data_quality",
    "interaction",
)

SPORT_PRIORITY = {
    "basketball": ("identity_strength", "performance_history", "form_load", "team_roster_context", "competition_context", "matchday_intelligence", "entity_profile", "data_quality", "interaction"),
    "volleyball": ("identity_strength", "performance_history", "form_load", "team_roster_context", "competition_context", "matchday_intelligence", "entity_profile", "data_quality", "interaction"),
    "valorant": ("identity_strength", "performance_history", "form_load", "team_roster_context", "competition_context", "matchday_intelligence", "entity_profile", "data_quality", "interaction"),
    "ufc": ("identity_strength", "performance_history", "entity_profile", "form_load", "competition_context", "matchday_intelligence", "data_quality", "interaction", "team_roster_context"),
    "rizin": ("identity_strength", "performance_history", "entity_profile", "form_load", "competition_context", "matchday_intelligence", "data_quality", "interaction", "team_roster_context"),
    "tennis": ("identity_strength", "performance_history", "entity_profile", "form_load", "competition_context", "matchday_intelligence", "data_quality", "interaction"),
    "f1": ("identity_strength", "performance_history", "entity_profile", "form_load", "competition_context", "matchday_intelligence", "data_quality", "interaction"),
    "rugby": ("identity_strength", "performance_history", "form_load", "team_roster_context", "competition_context", "matchday_intelligence", "entity_profile", "data_quality", "interaction"),
    "boxing": ("identity_strength", "performance_history", "entity_profile", "form_load", "competition_context", "matchday_intelligence", "data_quality", "interaction"),
}


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(name or "").lower()).strip("_")


def classify_feature(name: str) -> str:
    n = str(name or "").lower()
    if "_x_" in n or "interaction" in n:
        return "interaction"
    if any(k in n for k in ("coverage", "freshness", "source_", "pit_", "data_")):
        return "data_quality"
    if any(k in n for k in ("availability_", "lineup_", "injur", "travel", "weather", "market_", "news_", "late_")):
        return "matchday_intelligence"
    if n.startswith("competition_") or "__competition_" in n or any(k in n for k in ("__stage", "__round", "event_type")):
        return "competition_context"
    if any(k in n for k in ("profile__", "entity_profile__", "fighter.", "player.", "athlete.")):
        return "entity_profile"
    if any(k in n for k in ("roster", "starter", "__role", "__position", "team__")):
        return "team_roster_context"
    if any(k in n for k in ("stat_", "sig_str__", "takedown__", "td_pct__", "sub_attempts__", "control_time__", "attack__", "serve__", "receive__", "block__", "points__", "rebounds__", "assists__", "rating__", "acs__", "adr__", "kast__", "k_d__")):
        return "performance_history"
    if any(k in n for k in ("recent_", "streak", "rest_days", "games_last_", "short_rest", "margin_", "opponent_elo")):
        return "form_load"
    if any(k in n for k in ("elo", "history_n", "h2h_")):
        return "identity_strength"
    return "interaction" if "_x_" in n else "data_quality"


def family_members(feature_names: Iterable[str]) -> dict[str, list[str]]:
    out = {k: [] for k in FAMILY_ORDER}
    for name in feature_names:
        out.setdefault(classify_feature(name), []).append(str(name))
    return out


def _core_families(sport: str) -> tuple[str, ...]:
    priority = SPORT_PRIORITY.get(sport, FAMILY_ORDER)
    # Core remains deliberately small. Performance/form are added as explicit
    # challengers rather than silently becoming mandatory production inputs.
    return tuple(x for x in priority[:3] if x in FAMILY_ORDER)


def candidate_family_sets(sport: str, feature_names: Iterable[str], max_patterns: int = 14) -> list[dict]:
    families = family_members(feature_names)
    available = [x for x in SPORT_PRIORITY.get(sport, FAMILY_ORDER) if families.get(x)]
    if not available:
        return [{"pattern_id": "all_features", "families": [], "features": sorted(set(map(str, feature_names)))}]

    candidates: list[tuple[str, tuple[str, ...]]] = []
    core = tuple(x for x in _core_families(sport) if x in available)
    if core:
        candidates.append(("core", core))

    for family in available:
        if family not in core:
            candidates.append((f"core_plus_{family}", tuple(dict.fromkeys(core + (family,)))))
    for family_a, family_b in combinations(available, 2):
        if family_a in core and family_b in core:
            continue
        combo = tuple(dict.fromkeys(core + (family_a, family_b)))
        candidates.append((f"core_plus_{family_a}_plus_{family_b}", combo))

    candidates.append(("all_available_families", tuple(available)))

    out = []
    seen = set()
    for pattern_id, selected in candidates:
        if pattern_id in seen:
            continue
        seen.add(pattern_id)
        feats = sorted({f for fam in selected for f in families.get(fam, [])})
        if feats:
            out.append({"pattern_id": pattern_id, "families": list(selected), "features": feats})
        if len(out) >= int(max_patterns):
            break
    return out


def _metric(y: np.ndarray, p: np.ndarray) -> dict:
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    return {"logloss": ll, "n": int(len(y))}


def _pattern_model():
    return Pipeline([
        ("i", SimpleImputer(strategy="median", add_indicator=True)),
        ("s", StandardScaler()),
        ("m", LogisticRegression(max_iter=2500, C=0.25)),
    ])


def evaluate_patterns(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    sport: str,
    start: int,
    step: int,
    min_train: int = 80,
    max_patterns: int = 14,
) -> dict:
    """Chronological pre-holdout pattern screen.

    Every pattern is evaluated on identical walk-forward windows. The screen is
    intentionally model-light; downstream model selection still decides the
    production candidate. No holdout rows are accessed.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    candidates = candidate_family_sets(sport, feature_names, max_patterns=max_patterns)
    if len(candidates) < 2:
        return {"status": "SKIPPED", "reason": "too_few_feature_pattern_candidates", "candidates": candidates}

    folds = []
    end = max(int(start), int(min_train))
    while end < len(y):
        te = min(end + int(step), len(y))
        if te > end and len(np.unique(y[:end])) > 1 and len(np.unique(y[end:te])) > 1:
            folds.append((end, te))
        end = te
    if len(folds) < 3:
        return {"status": "SKIPPED", "reason": "too_few_preholdout_pattern_folds", "folds": len(folds), "candidates": candidates}

    results = {}
    for cand in candidates:
        idx = [feature_names.index(f) for f in cand["features"] if f in feature_names]
        if not idx:
            continue
        fold_scores = []
        for train_end, test_end in folds:
            Xtr = X[:train_end, idx]
            Xte = X[train_end:test_end, idx]
            model = _pattern_model()
            model.fit(Xtr, y[:train_end])
            p = model.predict_proba(Xte)[:, 1]
            fold_scores.append(_metric(y[train_end:test_end], p))
        if len(fold_scores) < 3:
            continue
        vals = np.asarray([x["logloss"] for x in fold_scores], dtype=float)
        recent_weights = np.linspace(1.0, 2.0, len(vals))
        robust = float(np.average(vals, weights=recent_weights) + 0.10 * np.std(vals))
        results[cand["pattern_id"]] = {
            "pattern_id": cand["pattern_id"],
            "families": cand["families"],
            "feature_count": len(idx),
            "folds": len(fold_scores),
            "logloss_mean": float(np.mean(vals)),
            "logloss_std": float(np.std(vals)),
            "recent_weighted_logloss": float(np.average(vals, weights=recent_weights)),
            "robust_objective": robust,
            "fold_logloss": vals.tolist(),
        }

    if not results:
        return {"status": "SKIPPED", "reason": "no_valid_pattern_results", "folds": len(folds), "candidates": candidates}

    ranked = sorted(results, key=lambda k: (
        results[k]["robust_objective"],
        results[k]["logloss_mean"],
        results[k]["feature_count"],
    ))
    best = ranked[0]
    baseline = results.get("all_available_families") or results.get("core")
    return {
        "status": "EVALUATED",
        "sport": sport,
        "fold_count": len(folds),
        "candidate_count": len(results),
        "ranked_pattern_ids": ranked,
        "results": results,
        "selected_pattern_id": best,
        "baseline_pattern_id": baseline["pattern_id"] if baseline else None,
        "selection_rule": "chronological_pre_holdout_logloss + recent-period weighting + dispersion penalty + feature-count tie-break",
        "holdout_touched": False,
    }


def select_features(pattern_report: dict, fallback: Iterable[str]) -> tuple[list[str], str]:
    fallback = sorted(set(map(str, fallback)))
    if isinstance(pattern_report, dict) and pattern_report.get("status") == "EVALUATED":
        selected = str(pattern_report.get("selected_pattern_id") or "")
        by_id = {
            str(x.get("pattern_id")): x
            for x in (pattern_report.get("candidates") or [])
            if isinstance(x, dict)
        }
        chosen = by_id.get(selected)
        if isinstance(chosen, dict) and chosen.get("features"):
            return sorted(set(map(str, chosen["features"]))), selected
    return fallback, "all_features_fallback"
