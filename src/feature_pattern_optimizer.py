from __future__ import annotations

"""Broad PIT-safe feature-pattern search.

The optimizer intentionally explores many *structured* representations rather
than brute-forcing arbitrary column subsets. Every candidate is evaluated on
the same chronological pre-holdout folds. The frozen holdout is never touched.
"""

import json
import math
import re
from itertools import combinations
from pathlib import Path
from typing import Iterable

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
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

PROFILE_TOKENS = ("profile__", "entity_profile__", "fighter.", "fighter_", "player.", "player_", "athlete.", "athlete_")
ROSTER_TOKENS = ("roster", "starter", "lineup", "position", "role", "team__", "availability")
PERFORMANCE_TOKENS = (
    "stat_", "sig_str__", "takedown__", "td_pct__", "sub_attempts__", "control_time__",
    "attack__", "serve__", "receive__", "block__", "error__", "sideout__",
    "points__", "rebounds__", "assists__", "steals__", "blocks__", "turnovers__",
    "fieldgoal", "threepoint", "freethrow", "rating__", "acs__", "adr__", "kast__", "k_d__",
)
FORM_TOKENS = ("recent_", "streak", "rest_days", "games_last_", "short_rest", "margin_", "opponent_elo")
STRENGTH_TOKENS = ("elo", "history_n", "h2h_")
CONTEXT_TOKENS = ("competition_", "__competition_", "stage", "round", "event_type", "rules_")
MATCHDAY_TOKENS = ("weather", "market_", "news_", "late_", "injur", "travel", "availability_", "lineup_")
QUALITY_TOKENS = ("coverage", "freshness", "source_", "pit_", "data_")
SUMMARY_SUFFIXES = ("mean", "median", "q25", "q75", "iqr", "last", "std", "trend", "ewma5", "n", "age_days", "relative")


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(name or "").lower()).strip("_")


def classify_feature(name: str) -> str:
    n = str(name or "").lower()
    if "_x_" in n or "interaction" in n:
        return "interaction"
    if any(k in n for k in QUALITY_TOKENS):
        return "data_quality"
    if any(k in n for k in MATCHDAY_TOKENS):
        return "matchday_intelligence"
    if any(k in n for k in CONTEXT_TOKENS) and not any(k in n for k in ("opponent_elo",)):
        return "competition_context"
    if any(k in n for k in PROFILE_TOKENS):
        return "entity_profile"
    if any(k in n for k in ROSTER_TOKENS):
        return "team_roster_context"
    if any(k in n for k in PERFORMANCE_TOKENS):
        return "performance_history"
    if any(k in n for k in FORM_TOKENS):
        return "form_load"
    if any(k in n for k in STRENGTH_TOKENS):
        return "identity_strength"
    return "data_quality"


def feature_subgroup(name: str) -> str:
    """Return a deterministic fine-grained block used to build structured patterns."""
    n = str(name or "")
    low = n.lower()
    family = classify_feature(n)
    if family == "performance_history":
        # Prefer the underlying statistic identity over a summary suffix.
        base = low
        for suffix in SUMMARY_SUFFIXES:
            base = re.sub(rf"__{re.escape(suffix)}$", "", base)
        base = re.sub(r"^[abd]__", "", base)
        return f"performance:{base}"
    if family == "entity_profile":
        base = re.sub(r"^(?:a|b|d)__", "", low)
        return f"profile:{base}"
    if family == "form_load":
        if any(x in low for x in ("rest_days", "games_last_", "short_rest")):
            return "form:load"
        if "margin" in low:
            return "form:margin"
        if "streak" in low:
            return "form:streak"
        if "recent_winrate" in low or "recent_form" in low:
            return "form:results"
        if "opponent_elo" in low:
            return "form:opponent_strength"
        return "form:other"
    if family == "identity_strength":
        if "h2h" in low:
            return "strength:h2h"
        if "elo_comp" in low:
            return "strength:competition_elo"
        if "elo" in low:
            return "strength:elo"
        return "strength:other"
    return f"{family}:all"


def family_members(feature_names: Iterable[str]) -> dict[str, list[str]]:
    out = {k: [] for k in FAMILY_ORDER}
    for name in feature_names:
        out.setdefault(classify_feature(name), []).append(str(name))
    return out


def subgroup_members(feature_names: Iterable[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name in feature_names:
        out.setdefault(feature_subgroup(name), []).append(str(name))
    return out


def _sport_priority(sport: str) -> tuple[str, ...]:
    return SPORT_PRIORITY.get(sport, FAMILY_ORDER)


def _representative_features(names: list[str], mode: str) -> list[str]:
    names = sorted(set(map(str, names)))
    if mode == "all":
        return names
    if mode == "diff_only":
        return [n for n in names if n.lower().startswith("d__")]
    if mode == "side_only":
        return [n for n in names if n.lower().startswith(("a__", "b__"))]
    if mode == "context_plus_diff":
        return [n for n in names if n.lower().startswith("d__") or classify_feature(n) in {"competition_context", "matchday_intelligence"}]
    if mode == "robust_summary":
        keep = ("mean", "median", "last", "ewma5", "trend", "n", "age_days")
        return [n for n in names if n.lower().endswith(tuple(f"__{x}" for x in keep)) or n.lower().startswith("d__elo")]
    if mode == "short_horizon":
        return [n for n in names if any(x in n.lower() for x in ("_5", "_7d", "_10", "short_rest", "last"))]
    if mode == "medium_horizon":
        return [n for n in names if any(x in n.lower() for x in ("_10", "_14d", "mean", "ewma5"))]
    if mode == "long_horizon":
        return [n for n in names if any(x in n.lower() for x in ("_20", "_30d", "history", "elo", "h2h"))]
    if mode == "structure_only":
        return [n for n in names if classify_feature(n) in {"identity_strength", "form_load", "performance_history", "entity_profile", "team_roster_context", "competition_context"}]
    if mode == "information_quality":
        return [n for n in names if classify_feature(n) in {"data_quality", "matchday_intelligence"} or n.lower().startswith("d__")]
    raise ValueError(f"unknown representation mode: {mode}")


def candidate_family_sets(sport: str, feature_names: Iterable[str], max_patterns: int = 14) -> list[dict]:
    """Backward-compatible family patterns plus a much broader structured grid."""
    features = sorted(set(map(str, feature_names)))
    families = family_members(features)
    available = [x for x in _sport_priority(sport) if families.get(x)]
    if not available:
        return [{"pattern_id": "all_features", "families": [], "features": features}]

    patterns: list[tuple[str, list[str], str]] = []
    priority = _sport_priority(sport)
    core = [x for x in priority[:3] if x in available]
    if core:
        patterns.append(("core", core, "all"))
    patterns.append(("all_available_families", available, "all"))
    for fam in available:
        patterns.append((f"only_{fam}", [fam], "all"))
        if fam not in core:
            patterns.append((f"core_plus_{fam}", list(dict.fromkeys(core + [fam])), "all"))
    for a, b in combinations(available, 2):
        combo = list(dict.fromkeys(core + [a, b]))
        patterns.append((f"core_plus_{a}_plus_{b}", combo, "all"))

    seen = set()
    out = []
    for pid, fams, rep in patterns:
        cols = sorted({f for fam in fams for f in families.get(fam, [])})
        if cols and pid not in seen:
            seen.add(pid)
            out.append({"pattern_id": pid, "families": fams, "representation": rep, "features": cols})
        if len(out) >= int(max_patterns):
            break
    return out


def broad_pattern_grid(sport: str, feature_names: Iterable[str], max_patterns: int = 128) -> list[dict]:
    """Generate a broad but structured pattern search space.

    The grid spans family subsets, fine-grained blocks, A/B/D representations,
    time-depth representations, profile/roster inclusion, quality signals and
    interaction toggles. Duplicate column sets are removed.
    """
    features = sorted(set(map(str, feature_names)))
    fam = family_members(features)
    sub = subgroup_members(features)
    available = [x for x in _sport_priority(sport) if fam.get(x)]
    priority = _sport_priority(sport)
    core = tuple(x for x in priority[:3] if x in available)
    candidates: list[dict] = []

    def add(pid: str, selected: Iterable[str], representation: str, note: str = "") -> None:
        selected = tuple(dict.fromkeys(x for x in selected if x in available))
        cols = sorted({f for x in selected for f in fam.get(x, [])})
        cols = _representative_features(cols, representation)
        if not cols:
            return
        key = tuple(cols)
        if any(tuple(c["features"]) == key for c in candidates):
            return
        candidates.append({
            "pattern_id": pid,
            "families": list(selected),
            "representation": representation,
            "feature_count": len(cols),
            "features": cols,
            "note": note,
        })

    reps = ("all", "diff_only", "side_only", "context_plus_diff", "robust_summary", "short_horizon", "medium_horizon", "long_horizon", "structure_only", "information_quality")

    # Global representations.
    for rep in reps:
        add(f"global__{rep}", available, rep)

    # Core ± one family, across meaningful representations.
    for rep in ("all", "diff_only", "robust_summary", "short_horizon", "medium_horizon", "long_horizon", "structure_only"):
        if core:
            add(f"core__{rep}", core, rep)
        for x in available:
            add(f"core_plus_{x}__{rep}", core + (x,), rep)

    # Leave-one-family-out patterns test whether added information is actually harmful.
    for x in available:
        remaining = tuple(y for y in available if y != x)
        add(f"loo_{x}", remaining, "all", "leave_one_family_out")

    # Pairwise and triple family interactions.
    pair_base = available[: min(8, len(available))]
    for r in (2, 3):
        for combo in combinations(pair_base, r):
            if core and not any(x in core for x in combo):
                continue
            add("families_" + "__".join(combo), combo, "all", "structured_family_subset")

    # Fine-grained subgroup search: strength + each performance/profile/form block.
    blocks = list(sub)
    strength_blocks = [x for x in blocks if x.startswith("strength:")]
    adjacent = [
        x for x in blocks
        if x.startswith(("performance:", "profile:", "form:", "team_roster_context:", "competition_context:"))
    ]
    base_blocks = strength_blocks[:3] + adjacent
    for block in base_blocks:
        names = sub.get(block, [])
        add(f"block__{block}", [classify_feature(n) for n in names], "all", "fine_grained_block")
    for a, b in combinations(base_blocks[:12], 2):
        names = sub.get(a, []) + sub.get(b, [])
        if names:
            cols = _representative_features(names, "all")
            if cols and not any(tuple(x["features"]) == tuple(cols) for x in candidates):
                candidates.append({
                    "pattern_id": f"subgroups__{a}__{b}",
                    "families": sorted({classify_feature(n) for n in names}),
                    "representation": "all",
                    "feature_count": len(cols),
                    "features": cols,
                    "note": "fine_grained_subgroup_pair",
                })

    # Stat-summary variants: raw/robust/recent emphasis for each performance subgroup.
    for block in [x for x in blocks if x.startswith("performance:")]:
        names = sub.get(block, [])
        for rep in ("all", "robust_summary", "short_horizon", "medium_horizon", "long_horizon", "diff_only"):
            cols = _representative_features(names, rep)
            if cols:
                candidates.append({
                    "pattern_id": f"statblock__{block}__{rep}",
                    "families": ["performance_history"],
                    "representation": rep,
                    "feature_count": len(cols),
                    "features": cols,
                    "note": "performance_stat_summary_variant",
                })

    # Profile / roster / quality toggles around the strongest three families.
    special_families = {
        "profile_on": tuple(x for x in available if x != "entity_profile"),
        "profile_off": tuple(x for x in available if x != "entity_profile"),
        "roster_on": tuple(x for x in available if x != "team_roster_context"),
        "roster_off": tuple(x for x in available if x != "team_roster_context"),
        "quality_off": tuple(x for x in available if x != "data_quality"),
        "interaction_off": tuple(x for x in available if x != "interaction"),
    }
    for label, fams in special_families.items():
        if label == "profile_on" and "entity_profile" in available:
            fams = tuple(dict.fromkeys(fams + ("entity_profile",)))
        if label == "roster_on" and "team_roster_context" in available:
            fams = tuple(dict.fromkeys(fams + ("team_roster_context",)))
        add(label, fams, "all", "toggle_family")

    # Explicit combination of all core information with/without low-reliability families.
    high_trust = tuple(x for x in available if x not in {"data_quality", "interaction"})
    add("high_trust_no_meta", high_trust, "all")
    add("high_trust_diff", high_trust, "diff_only")
    add("high_trust_robust", high_trust, "robust_summary")

    # Cap deterministically after a wide search; keep diverse pattern classes first.
    return candidates[: max(1, int(max_patterns))]


def _metric(y: np.ndarray, p: np.ndarray) -> dict:
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    brier = float(np.mean((p - y) ** 2))
    return {"logloss": ll, "brier": brier, "n": int(len(y))}


def _pattern_model(kind: str = "logistic"):
    if kind == "logistic":
        return Pipeline([
            ("i", SimpleImputer(strategy="median", add_indicator=True)),
            ("s", StandardScaler()),
            ("m", LogisticRegression(max_iter=1600, C=0.25, solver="liblinear")),
        ])
    if kind == "hist_gb":
        return Pipeline([
            ("i", SimpleImputer(strategy="median", add_indicator=True)),
            ("m", HistGradientBoostingClassifier(
                max_iter=180, learning_rate=0.05, l2_regularization=2.0,
                max_leaf_nodes=15, random_state=91,
            )),
        ])
    if kind == "extra_trees":
        return Pipeline([
            ("i", SimpleImputer(strategy="median", add_indicator=True)),
            ("m", ExtraTreesClassifier(
                n_estimators=180, min_samples_leaf=5, max_features="sqrt",
                n_jobs=1, class_weight="balanced", random_state=92,
            )),
        ])
    raise ValueError(f"unknown pattern model: {kind}")


def _folds(n: int, start: int, step: int) -> list[tuple[int, int]]:
    out = []
    end = max(80, int(start))
    while end < int(n):
        te = min(end + max(10, int(step)), int(n))
        if te > end:
            out.append((end, te))
        end = te
    return out


def _evaluate_one_pattern(X, y, idx, folds, model_kind):
    scores = []
    for train_end, test_end in folds:
        ytr = y[:train_end]
        yte = y[train_end:test_end]
        if len(np.unique(ytr)) < 2 or len(np.unique(yte)) < 2:
            continue
        model = _pattern_model(model_kind)
        model.fit(X[:train_end, idx], ytr)
        p = model.predict_proba(X[train_end:test_end, idx])[:, 1]
        scores.append(_metric(yte, p))
    return scores


def _robust_score(fold_scores: list[dict]) -> dict:
    vals = np.asarray([x["logloss"] for x in fold_scores], dtype=float)
    bri = np.asarray([x["brier"] for x in fold_scores], dtype=float)
    if len(vals) == 0:
        return {"status": "NO_FOLDS"}
    weights = np.linspace(1.0, 2.5, len(vals))
    recent_ll = float(np.average(vals, weights=weights))
    robust = float(recent_ll + 0.12 * np.std(vals))
    return {
        "status": "EVALUATED",
        "logloss_mean": float(np.mean(vals)),
        "logloss_std": float(np.std(vals)),
        "recent_weighted_logloss": recent_ll,
        "brier_mean": float(np.mean(bri)),
        "recent_weighted_brier": float(np.average(bri, weights=weights)),
        "robust_objective": robust,
        "fold_logloss": vals.tolist(),
        "fold_brier": bri.tolist(),
    }


def _paired_bootstrap(delta: list[float], seed: int = 20261004) -> dict:
    d = np.asarray(delta, dtype=float)
    if len(d) < 6 or not np.isfinite(d).all():
        return {
            "folds": int(len(d)),
            "mean_delta": float(np.mean(d)) if len(d) else None,
            "bootstrap_prob_improvement": None,
            "bootstrap_p05_improvement": None,
        }
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(2000, len(d)))
    boot_delta = d[idx].mean(axis=1)
    improvement = -boot_delta
    return {
        "folds": int(len(d)),
        "mean_delta": float(d.mean()),
        "se": float(d.std(ddof=1) / math.sqrt(len(d))),
        "bootstrap_prob_improvement": float(np.mean(improvement > 0)),
        "bootstrap_p05_improvement": float(np.quantile(improvement, 0.05)),
    }


def evaluate_patterns(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    sport: str,
    start: int,
    step: int,
    min_train: int = 80,
    max_patterns: int = 128,
    stage2_top_k: int = 12,
) -> dict:
    """Multi-stage chronological pattern search.

    Stage 1 is broad/cheap logistic screening. Stage 2 retests the strongest
    diverse candidates with HistGradientBoosting and ExtraTrees. Only pre-holdout
    rows are used. The holdout remains score-only downstream.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    if X.ndim != 2 or len(X) != len(y):
        return {"status": "FAILED", "reason": "invalid_pattern_matrix_shape"}
    candidates = broad_pattern_grid(sport, feature_names, max_patterns=max_patterns)
    if len(candidates) < 2:
        return {"status": "SKIPPED", "reason": "too_few_structured_pattern_candidates", "candidates": candidates}
    folds = _folds(len(y), start, step)
    folds = [f for f in folds if len(np.unique(y[f[0]:f[1]])) > 1]
    if len(folds) < 3:
        return {
            "status": "SKIPPED",
            "reason": "too_few_preholdout_pattern_folds",
            "folds": len(folds),
            "candidate_count": len(candidates),
        }

    stage1 = {}
    for cand in candidates:
        idx = [feature_names.index(f) for f in cand["features"] if f in feature_names]
        if not idx:
            continue
        scores = _evaluate_one_pattern(X, y, idx, folds, "logistic")
        summary = _robust_score(scores)
        if summary.get("status") == "EVALUATED":
            stage1[cand["pattern_id"]] = {
                **cand,
                **summary,
                "stage": 1,
                "model": "logistic",
            }

    if not stage1:
        return {"status": "SKIPPED", "reason": "no_stage1_pattern_results", "candidate_count": len(candidates)}

    ranked1 = sorted(stage1, key=lambda k: (
        stage1[k]["robust_objective"],
        stage1[k]["recent_weighted_brier"],
        stage1[k]["feature_count"],
    ))
    top1 = ranked1[: max(4, int(stage2_top_k))]
    stage2 = {}
    for pid in top1:
        cand = stage1[pid]
        idx = [feature_names.index(f) for f in cand["features"] if f in feature_names]
        for model_kind in ("hist_gb", "extra_trees"):
            scores = _evaluate_one_pattern(X, y, idx, folds, model_kind)
            summary = _robust_score(scores)
            if summary.get("status") != "EVALUATED":
                continue
            stage2[f"{pid}__{model_kind}"] = {
                **cand,
                **summary,
                "stage": 2,
                "model": model_kind,
            }

    # A pattern is selected from the multi-model stage only when it is available;
    # otherwise stage-1 evidence is retained as a research-only fallback.
    stage2_ranked = sorted(stage2, key=lambda k: (
        stage2[k]["robust_objective"],
        stage2[k]["recent_weighted_brier"],
        stage2[k]["feature_count"],
    ))
    selected_record = stage2[stage2_ranked[0]] if stage2_ranked else stage1[ranked1[0]]
    baseline = stage1.get("global__all") or stage1.get("all_available_families")
    if baseline is None:
        baseline = stage1[ranked1[-1]]

    # Paired fold evidence against the all-feature baseline when possible.
    selected_idx = [feature_names.index(f) for f in selected_record["features"] if f in feature_names]
    base_idx = [feature_names.index(f) for f in baseline["features"] if f in feature_names]
    paired_delta = []
    for train_end, test_end in folds:
        if len(np.unique(y[:train_end])) < 2 or len(np.unique(y[train_end:test_end])) < 2:
            continue
        selected_model = _pattern_model("logistic")
        base_model = _pattern_model("logistic")
        selected_model.fit(X[:train_end, selected_idx], y[:train_end])
        base_model.fit(X[:train_end, base_idx], y[:train_end])
        ps = selected_model.predict_proba(X[train_end:test_end, selected_idx])[:, 1]
        pb = base_model.predict_proba(X[train_end:test_end, base_idx])[:, 1]
        paired_delta.append(
            float(
                _metric(y[train_end:test_end], ps)["logloss"]
                - _metric(y[train_end:test_end], pb)["logloss"]
            )
        )

    baseline_ll = float(baseline["logloss_mean"])
    selected_ll = float(selected_record["logloss_mean"])
    relative_improvement = float((baseline_ll - selected_ll) / max(abs(baseline_ll), 1e-12))
    bootstrap = _paired_bootstrap(paired_delta)

    return {
        "status": "EVALUATED",
        "sport": sport,
        "fold_count": len(folds),
        "candidate_count": len(candidates),
        "stage1_candidate_count": len(stage1),
        "stage2_candidate_count": len(stage2),
        "stage1_ranked": ranked1[: min(25, len(ranked1))],
        "stage2_ranked": stage2_ranked[: min(25, len(stage2_ranked))],
        "selected_pattern": selected_record,
        "selected_pattern_id": selected_record["pattern_id"],
        "baseline_pattern": {
            "pattern_id": baseline["pattern_id"],
            "feature_count": baseline["feature_count"],
            "logloss_mean": baseline["logloss_mean"],
            "robust_objective": baseline["robust_objective"],
        },
        "relative_logloss_improvement_vs_baseline": relative_improvement,
        "paired_fold_deltas_selected_minus_baseline": paired_delta,
        "paired_bootstrap": bootstrap,
        "selection_rule": (
            "stage1 broad structured logistic screen; stage2 top-pattern HistGradientBoosting/ExtraTrees; "
            "recent-weighted LogLoss + dispersion penalty; lower feature count only as tie-break"
        ),
        "holdout_touched": False,
        "production_adoption": "NOT_AUTHORIZED_BY_PATTERN_SCREEN_ALONE",
    }


def select_features(pattern_report: dict, fallback: Iterable[str]) -> tuple[list[str], str]:
    fallback = sorted(set(map(str, fallback)))
    if not (isinstance(pattern_report, dict) and pattern_report.get("status") == "EVALUATED"):
        return fallback, "all_features_fallback"

    rec = pattern_report.get("selected_pattern")
    baseline = pattern_report.get("baseline_pattern") or {}
    rel = pattern_report.get("relative_logloss_improvement_vs_baseline")
    boot = pattern_report.get("paired_bootstrap") or {}
    try:
        rel = float(rel)
    except (TypeError, ValueError):
        rel = float("-inf")
    prob = boot.get("bootstrap_prob_improvement")
    p05 = boot.get("bootstrap_p05_improvement")
    try:
        prob = float(prob) if prob is not None else None
    except (TypeError, ValueError):
        prob = None
    try:
        p05 = float(p05) if p05 is not None else None
    except (TypeError, ValueError):
        p05 = None

    # The screen is allowed to reject a pattern even after extensive search.
    # Apply only when paired chronological evidence is directionally stable; for
    # small samples the downstream full OOS pipeline must remain on all features.
    folds = int(pattern_report.get("fold_count") or 0)
    baseline_count = int(baseline.get("feature_count") or len(fallback))
    selected_count = int((rec or {}).get("feature_count") or 0)
    stable = folds >= 6 and rel >= 0.005
    if prob is not None:
        stable = stable and prob >= 0.75
    if p05 is not None:
        stable = stable and p05 > 0.0
    simpler_or_equal = selected_count <= baseline_count

    if isinstance(rec, dict) and rec.get("features") and stable and simpler_or_equal:
        return sorted(set(map(str, rec["features"]))), str(rec.get("pattern_id") or "selected_pattern")
    return fallback, "all_features_fallback"


__all__ = [
    "FAMILY_ORDER",
    "SPORT_PRIORITY",
    "classify_feature",
    "feature_subgroup",
    "family_members",
    "subgroup_members",
    "candidate_family_sets",
    "broad_pattern_grid",
    "evaluate_patterns",
    "select_features",
]
