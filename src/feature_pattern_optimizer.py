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
from sklearn.feature_selection import mutual_info_classif
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


SUPPORTED_SPORTS = (
    "valorant", "basketball", "volleyball", "tennis", "ufc",
    "rizin", "f1", "rugby", "boxing",
)

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
    # Derived orientation/ratio encodings inherit the semantic family of the
    # underlying feature whenever possible (e.g. AD__points, R__recent_winrate).
    n = re.sub(r"^(?:a|b|d|ad|m|r|q)__", "", n)
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
    if mode == "derived_only":
        return [n for n in names if n.lower().startswith(("d__", "ad__", "m__", "r__", "q__"))]
    if mode == "raw_only":
        return [n for n in names if n.lower().startswith(("a__", "b__"))]
    if mode == "last_only":
        return [n for n in names if "__last" in n.lower() or n.lower().startswith(("d__elo", "d__recent_"))]
    if mode == "trend_only":
        return [n for n in names if any(x in n.lower() for x in ("__trend", "momentum", "delta"))]
    if mode == "dispersion_only":
        return [n for n in names if any(x in n.lower() for x in ("__std", "__iqr", "__q25", "__q75"))]
    if mode == "count_age_only":
        return [n for n in names if any(x in n.lower() for x in ("__n", "age_days", "history_n", "coverage"))]
    if mode == "profile_roster_context":
        return [n for n in names if classify_feature(n) in {"entity_profile", "team_roster_context", "competition_context", "matchday_intelligence"}]
    if mode == "performance_form":
        return [n for n in names if classify_feature(n) in {"performance_history", "form_load"}]
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


def broad_pattern_grid(sport: str, feature_names: Iterable[str], max_patterns: int = 1024) -> list[dict]:
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

    reps = ("all", "diff_only", "side_only", "context_plus_diff", "robust_summary", "short_horizon", "medium_horizon", "long_horizon", "structure_only", "information_quality", "derived_only", "raw_only", "last_only", "trend_only", "dispersion_only", "count_age_only", "profile_roster_context", "performance_form")

    # Global representations.
    for rep in reps:
        add(f"global__{rep}", available, rep)

    # Core ± one family, across meaningful representations.
    for rep in ("all", "diff_only", "robust_summary", "short_horizon", "medium_horizon", "long_horizon", "structure_only", "derived_only", "raw_only", "last_only", "trend_only", "dispersion_only", "performance_form"):
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

    # Add systematic family-subset × representation patterns. This is still
    # structured search, not arbitrary feature powersets.
    max_r = min(4, len(available))
    for rsize in range(1, max_r + 1):
        for combo in combinations(available, rsize):
            for rep in ("all", "diff_only", "robust_summary", "short_horizon", "medium_horizon", "long_horizon"):
                add(
                    "subset_" + str(rsize) + "__" + "__".join(combo) + "__" + rep,
                    combo,
                    rep,
                    "systematic_family_subset_representation",
                )

    # Heterogeneous family-specific representations: different information
    # families can prefer different temporal/structural views. This avoids the
    # restrictive assumption that every selected family must use the same encoding.
    heterogeneous_reps = (
        ("all", "all", "all", "all"),
        ("short_horizon", "medium_horizon", "long_horizon", "robust_summary"),
        ("robust_summary", "short_horizon", "medium_horizon", "all"),
        ("diff_only", "short_horizon", "robust_summary", "information_quality"),
        ("derived_only", "medium_horizon", "short_horizon", "all"),
        ("raw_only", "robust_summary", "long_horizon", "context_plus_diff"),
        ("last_only", "trend_only", "dispersion_only", "count_age_only"),
        ("performance_form", "short_horizon", "performance_form", "profile_roster_context"),
    )
    hetero_family_sizes = range(2, min(4, len(available)) + 1)
    for rsize in hetero_family_sizes:
        for combo_index, combo in enumerate(combinations(available, rsize)):
            combo = tuple(combo)
            for template_index, template in enumerate(heterogeneous_reps):
                selected_cols = []
                assignments = []
                for idx, fam_name in enumerate(combo):
                    rep = template[idx % len(template)]
                    fam_cols = fam.get(fam_name, [])
                    selected_cols.extend(_representative_features(fam_cols, rep))
                    assignments.append(f"{fam_name}={rep}")
                if selected_cols:
                    candidates.append({
                        "pattern_id": "hetero__" + str(rsize) + "__" + str(combo_index) + "__t" + str(template_index),
                        "families": list(combo),
                        "representation": "heterogeneous",
                        "feature_count": len(set(selected_cols)),
                        "features": sorted(set(selected_cols)),
                        "note": "family_specific_representation:" + "|".join(assignments),
                    })

    # Add fine-grained subgroup × family controls.
    subgroup_names = sorted(sub)
    for block in subgroup_names:
        block_features = sub.get(block, [])
        if not block_features:
            continue
        fam_name = classify_feature(block_features[0])
        cols = _representative_features(block_features, "all")
        if cols:
            candidates.append({
                "pattern_id": "single_subgroup__" + block,
                "families": [fam_name],
                "representation": "all",
                "feature_count": len(cols),
                "features": cols,
                "note": "single_fine_grained_information_block",
            })
        for rep in ("robust_summary", "short_horizon", "medium_horizon", "long_horizon", "diff_only"):
            cols = _representative_features(block_features, rep)
            if cols:
                candidates.append({
                    "pattern_id": "single_subgroup__" + block + "__" + rep,
                    "families": [fam_name],
                    "representation": rep,
                    "feature_count": len(cols),
                    "features": cols,
                    "note": "single_fine_grained_information_block_representation",
                })

    # Deterministic diversity cap: retain distinct search classes before filling
    # the remaining budget. This prevents early global patterns from crowding out
    # later profile, roster and performance-stat tests.
    budget = max(1, int(max_patterns))
    selected = []
    seen_keys = set()
    bucket_rules = (
        ("global", lambda p: str(p.get("pattern_id","")).startswith("global__")),
        ("systematic", lambda p: p.get("note") == "systematic_family_subset_representation"),
        ("fine", lambda p: str(p.get("note","")).startswith("fine_grained")),
        ("performance", lambda p: p.get("note") == "performance_stat_summary_variant"),
        ("toggle", lambda p: p.get("note") == "toggle_family"),
        ("loo", lambda p: p.get("note") == "leave_one_family_out"),
        ("structured", lambda p: p.get("note") == "structured_family_subset"),
    )
    for _, matcher in bucket_rules:
        for cand in candidates:
            if not matcher(cand):
                continue
            key = tuple(cand.get("features") or [])
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            selected.append(cand)
            if len(selected) >= budget:
                return selected
    for cand in candidates:
        key = tuple(cand.get("features") or [])
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        selected.append(cand)
        if len(selected) >= budget:
            break
    return selected


def _rank_feature_views(X: np.ndarray, y: np.ndarray, feature_names: list[str]) -> dict[str, list[str]]:
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    empty = {"corr": [], "spearman": [], "mutual_info": [], "logistic_coef": [], "tree_importance": []}
    if len(y) < 80 or X.ndim != 2 or X.shape[1] != len(feature_names):
        return empty
    Xi = SimpleImputer(strategy="median", add_indicator=False).fit_transform(X)
    names = list(feature_names)
    corr = np.zeros(Xi.shape[1], dtype=float)
    spearman = np.zeros(Xi.shape[1], dtype=float)
    for j in range(Xi.shape[1]):
        x = Xi[:, j]
        sx = float(np.std(x))
        sy = float(np.std(y))
        if sx > 1e-12 and sy > 1e-12:
            corr[j] = float(np.nan_to_num(abs(np.corrcoef(x, y)[0, 1]), nan=0.0, posinf=0.0, neginf=0.0))
            rx = np.argsort(np.argsort(x, kind="mergesort"), kind="mergesort").astype(float)
            ry = np.argsort(np.argsort(y, kind="mergesort"), kind="mergesort").astype(float)
            spearman[j] = float(np.nan_to_num(abs(np.corrcoef(rx, ry)[0, 1]), nan=0.0, posinf=0.0, neginf=0.0))
    try:
        mi = np.nan_to_num(
            mutual_info_classif(Xi, y, discrete_features=False, random_state=20261004),
            nan=0.0, posinf=0.0, neginf=0.0,
        )
    except Exception:
        mi = np.zeros(Xi.shape[1], dtype=float)
    try:
        logistic = Pipeline([
            ("s", StandardScaler()),
            ("m", LogisticRegression(max_iter=1400, C=0.2, solver="liblinear")),
        ]).fit(Xi, y)
        coef = np.nan_to_num(np.abs(logistic.named_steps["m"].coef_[0]), nan=0.0, posinf=0.0, neginf=0.0)
    except Exception:
        coef = np.zeros(Xi.shape[1], dtype=float)
    try:
        tree = ExtraTreesClassifier(
            n_estimators=180, min_samples_leaf=8, max_features="sqrt",
            class_weight="balanced", n_jobs=1, random_state=20261005,
        ).fit(Xi, y)
        imp = np.nan_to_num(tree.feature_importances_, nan=0.0, posinf=0.0, neginf=0.0)
    except Exception:
        imp = np.zeros(Xi.shape[1], dtype=float)

    def order(scores):
        return [names[i] for i in np.argsort(-np.asarray(scores), kind="mergesort")]

    return {
        "corr": order(corr),
        "spearman": order(spearman),
        "mutual_info": order(mi),
        "logistic_coef": order(coef),
        "tree_importance": order(imp),
    }



def _feature_ranking_candidates(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    families: dict[str, list[str]],
    max_additional: int = 512,
) -> list[dict]:
    """Generate sparse/rich candidates from several outcome-aware ranking views.

    Ranking is computed only inside the pattern-selection prefix. Stability views
    re-fit the rankers on multiple earlier prefixes of that prefix and reward
    features that recur, reducing one-window selection noise.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    if len(y) < 120 or X.ndim != 2 or X.shape[1] != len(feature_names):
        return []

    views = _rank_feature_views(X, y, feature_names)
    if not any(views.values()):
        return []
    names = list(feature_names)
    out = []
    seen = set()

    def add(pid, cols, note):
        cols = [str(x) for x in cols if str(x) in names]
        cols = list(dict.fromkeys(cols))
        if not cols:
            return
        key = tuple(sorted(cols))
        if key in seen:
            return
        seen.add(key)
        out.append({
            "pattern_id": pid,
            "families": sorted({classify_feature(x) for x in cols}),
            "representation": "ranked_subset",
            "feature_count": len(cols),
            "features": sorted(cols),
            "note": note,
        })

    sizes = tuple(k for k in (8, 16, 24, 32, 48, 64, 96, 128, 192, 256) if k < len(names)) + (len(names),)
    for rname, ranked in views.items():
        for k in sizes:
            add(f"rank__{rname}__top{k}", ranked[:k], "outcome_ranked_top_k")

    top_sizes = [k for k in (16, 32, 64, 128] if k <= len(names)]
    ranker_names = ("corr", "spearman", "mutual_info", "logistic_coef", "tree_importance")
    for k in top_sizes:
        sets = [set(views[x][:k]) for x in ranker_names]
        add(f"rank__union5__top{k}", sorted(set.union(*sets)), "union_of_five_rankers")
        add(f"rank__intersection5__top{k}", sorted(set.intersection(*sets)), "intersection_of_five_rankers")
        for a_idx in range(len(ranker_names)):
            for b_idx in range(a_idx + 1, len(ranker_names)):
                ra, rb = ranker_names[a_idx], ranker_names[b_idx]
                add(f"rank__{ra}_{rb}__top{k}", sorted(sets[a_idx] & sets[b_idx]), "intersection_pair_rankers")

    # Stability across multiple earlier prefixes of the selection period.
    prefix_fracs = (0.55, 0.70, 0.85, 1.0)
    for rname in ("corr", "spearman", "mutual_info", "logistic_coef", "tree_importance"):
        for k in (16, 32, 64):
            counts = {name: 0 for name in names}
            used = 0
            for frac in prefix_fracs:
                cut = max(80, min(len(y), int(len(y) * frac)))
                if cut < 80 or len(np.unique(y[:cut])) < 2:
                    continue
                view = _rank_feature_views(X[:cut], y[:cut], feature_names).get(rname, [])
                if not view:
                    continue
                used += 1
                for name in view[:k]:
                    counts[name] += 1
            for threshold in (2, 3, 4):
                if used >= threshold:
                    stable = [name for name in names if counts.get(name, 0) >= threshold]
                    stable = sorted(stable, key=lambda n: (-counts[n], n))
                    add(
                        f"stability__{rname}__top{k}__ge{threshold}",
                        stable,
                        "multi_prefix_rank_stability",
                    )

    # Stability consensus across rankers and prefixes.
    stability_sets = []
    for rname in ("corr", "spearman", "mutual_info", "logistic_coef", "tree_importance"):
        for k in (16, 32, 64):
            counts = {name: 0 for name in names}
            for frac in prefix_fracs[:3]:
                cut = max(80, min(len(y), int(len(y) * frac)))
                view = _rank_feature_views(X[:cut], y[:cut], feature_names).get(rname, [])
                for name in view[:k]:
                    counts[name] += 1
            stability_sets.append(set(n for n, cnt in counts.items() if cnt >= 2))
    if stability_sets:
        add("stability__ranker_consensus", sorted(set.intersection(*stability_sets)), "stable_multi_ranker_consensus")
        add("stability__ranker_union", sorted(set.union(*stability_sets)), "stable_multi_ranker_union")

    # Family-balanced selections using multiple ranking views.
    for per_family in (2, 4, 6, 8, 12):
        for rname in ("corr", "spearman", "mutual_info", "logistic_coef", "tree_importance"):
            cols = []
            ranked = views[rname]
            for _, fam_cols in sorted(families.items()):
                available = set(fam_cols)
                cols.extend([n for n in ranked if n in available][:per_family])
            add(
                f"rank__family_balanced__{rname}__{per_family}",
                cols,
                "family_balanced_rank",
            )

    return out[: max(1, int(max_additional))]


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
    if kind == "hist_gb_shallow":
        return Pipeline([
            ("i", SimpleImputer(strategy="median", add_indicator=True)),
            ("m", HistGradientBoostingClassifier(
                max_iter=140, learning_rate=0.08, l2_regularization=3.0,
                max_leaf_nodes=7, min_samples_leaf=15, random_state=93,
            )),
        ])
    if kind == "extra_trees_wide":
        return Pipeline([
            ("i", SimpleImputer(strategy="median", add_indicator=True)),
            ("m", ExtraTreesClassifier(
                n_estimators=220, min_samples_leaf=8, max_features=0.7,
                n_jobs=1, class_weight="balanced", random_state=94,
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
    max_patterns: int = 1024,
    stage2_top_k: int = 32,
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
    base_budget = max(256, min(int(max_patterns), 1024))
    # Build chronological evaluation folds BEFORE any outcome-aware candidate
    # generation. Rankers are fit only on the first training window of the
    # selection folds; they must never see labels from their own test windows.
    folds = _folds(len(y), start, step)
    folds = [f for f in folds if len(np.unique(y[f[0]:f[1]])) > 1]
    if len(folds) < 4:
        return {
            "status": "SKIPPED",
            "reason": "too_few_preholdout_pattern_folds",
            "folds": len(folds),
        }
    # Nested inner confirmation: broad candidate screening uses the earlier
    # folds, while the final pattern/model choice is confirmed on untouched
    # later folds inside the same pre-holdout prefix. This reduces winner's
    # curse from searching hundreds of candidates.
    confirmation_count = 3 if len(folds) >= 6 else 2
    screen_folds = folds[:-confirmation_count]
    confirmation_folds = folds[-confirmation_count:]
    if len(screen_folds) < 2:
        return {
            "status": "SKIPPED",
            "reason": "too_few_pattern_screen_folds_after_confirmation_split",
            "folds": len(folds),
            "screen_folds": len(screen_folds),
            "confirmation_folds": len(confirmation_folds),
        }
    ranker_fit_end = int(screen_folds[0][0])
    if ranker_fit_end < max(int(min_train), 80):
        return {
            "status": "SKIPPED",
            "reason": "pattern_ranker_training_window_too_small",
            "ranker_fit_rows": ranker_fit_end,
        }

    candidates = broad_pattern_grid(sport, feature_names, max_patterns=base_budget)
    families = family_members(feature_names)
    ranked_candidates = _feature_ranking_candidates(
        X[:ranker_fit_end],
        y[:ranker_fit_end],
        feature_names,
        families,
        max_additional=max(256, base_budget // 2),
    )
    candidates.extend(ranked_candidates)
    # Deduplicate after adding outcome-ranked candidates, then keep a wide,
    # deterministic search budget.
    deduped = []
    seen_cols = set()
    for cand in candidates:
        key = tuple(cand.get("features") or [])
        if not key or key in seen_cols:
            continue
        seen_cols.add(key)
        deduped.append(cand)
        if len(deduped) >= base_budget:
            break
    candidates = deduped
    if len(candidates) < 2:
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
        scores = _evaluate_one_pattern(X, y, idx, screen_folds, "logistic")
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
    top1 = ranked1[: max(8, int(stage2_top_k))]
    stage2 = {}
    for pid in top1:
        cand = stage1[pid]
        idx = [feature_names.index(f) for f in cand["features"] if f in feature_names]
        for model_kind in ("hist_gb", "hist_gb_shallow", "extra_trees", "extra_trees_wide"):
            scores = _evaluate_one_pattern(X, y, idx, confirmation_folds, model_kind)
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

    # Paired fold evidence must use the SAME model family as the selected
    # pattern. Otherwise a stage-2 tree winner would be compared to a
    # logistic baseline, making the adoption signal methodologically invalid.
    selected_model_kind = str(selected_record.get("model") or "logistic")
    selected_idx = [feature_names.index(f) for f in selected_record["features"] if f in feature_names]
    base_idx = [feature_names.index(f) for f in baseline["features"] if f in feature_names]
    paired_delta = []
    aligned_baseline_scores = []
    aligned_selected_scores = []
    for train_end, test_end in confirmation_folds:
        if len(np.unique(y[:train_end])) < 2 or len(np.unique(y[train_end:test_end])) < 2:
            continue
        selected_model = _pattern_model(selected_model_kind)
        base_model = _pattern_model(selected_model_kind)
        selected_model.fit(X[:train_end, selected_idx], y[:train_end])
        base_model.fit(X[:train_end, base_idx], y[:train_end])
        ps = selected_model.predict_proba(X[train_end:test_end, selected_idx])[:, 1]
        pb = base_model.predict_proba(X[train_end:test_end, base_idx])[:, 1]
        ms = _metric(y[train_end:test_end], ps)
        mb = _metric(y[train_end:test_end], pb)
        paired_delta.append(float(ms["logloss"] - mb["logloss"]))
        aligned_baseline_scores.append(mb)
        aligned_selected_scores.append(ms)

    baseline_aligned_summary = _robust_score(aligned_baseline_scores)
    selected_aligned_summary = _robust_score(aligned_selected_scores)
    baseline_ll = float(baseline_aligned_summary.get("logloss_mean", baseline["logloss_mean"]))
    selected_ll = float(selected_aligned_summary.get("logloss_mean", selected_record["logloss_mean"]))
    relative_improvement = float((baseline_ll - selected_ll) / max(abs(baseline_ll), 1e-12))
    bootstrap = _paired_bootstrap(paired_delta)


    return {
        "status": "EVALUATED",
        "sport": sport,
        "fold_count": len(folds),
        "screen_fold_count": len(screen_folds),
        "confirmation_fold_count": len(confirmation_folds),
        "confirmation_folds_start": [int(a) for a, _ in confirmation_folds],
        "candidate_count": len(candidates),
        "stage1_candidate_count": len(stage1),
        "stage1_ranker_candidate_count": len(ranked_candidates),
        "ranker_fit_rows": int(ranker_fit_end),
        "ranker_fit_excludes_first_test_fold": True,
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
        "confirmation_non_degraded_fraction": (
            float(np.mean(np.asarray(paired_delta) <= 0.0)) if paired_delta else None
        ),
        "selected_model_kind": selected_model_kind,
        "baseline_aligned_to_selected_model": baseline_aligned_summary,
        "selected_aligned_summary": selected_aligned_summary,
        "paired_bootstrap": bootstrap,
        "selection_rule": (
            "rankers fit only on the first chronological training window; stage1 broad structured logistic screen "
            "on earlier inner folds; stage2 top-pattern HistGradientBoosting/ExtraTrees confirmed on later inner folds; "
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
    confirmation_folds = int(pattern_report.get("confirmation_fold_count") or 0)
    non_degraded = pattern_report.get("confirmation_non_degraded_fraction")
    try:
        non_degraded = float(non_degraded) if non_degraded is not None else None
    except (TypeError, ValueError):
        non_degraded = None
    stable = (
        folds >= 6
        and confirmation_folds >= 3
        and rel >= 0.005
        and (non_degraded is None or non_degraded >= (2.0 / 3.0))
    )
    if prob is not None:
        stable = stable and prob >= 0.75
    if p05 is not None:
        stable = stable and p05 > 0.0
    simpler_or_equal = selected_count <= baseline_count

    if isinstance(rec, dict) and rec.get("features") and stable and simpler_or_equal:
        return sorted(set(map(str, rec["features"]))), str(rec.get("pattern_id") or "selected_pattern")
    return fallback, "all_features_fallback"


__all__ = [
    "SUPPORTED_SPORTS",
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
