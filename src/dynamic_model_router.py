from __future__ import annotations
"""
Leakage-safe dynamic model router.

The router is deliberately challenger-only: it is trained from chronological
out-of-fold base-model predictions and PIT-safe context, then compared against
the incumbent fixed ensemble. It never sees the frozen holdout during selector
training. Promotion remains controlled by research_cycle_strict.py.
"""
from typing import Dict, Iterable, List, Sequence, Tuple
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def _metric(y, p):
    y = np.asarray(y)
    p = np.clip(np.asarray(p), 1e-6, 1 - 1e-6)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    br = float(np.mean((p - y) ** 2))
    ece = 0.0
    for lo, hi in zip(np.linspace(0, 1, 10, endpoint=False), np.linspace(0, 1, 10)):
        mask = (p >= lo) & ((p < hi) if hi < 1 else (p <= hi))
        if np.any(mask):
            ece += float(mask.mean()) * abs(float(y[mask].mean()) - float(p[mask].mean()))
    return {"logloss": ll, "brier": br, "ece": float(ece), "accuracy": float(np.mean((p >= .5) == y)), "n": int(len(y))}


def _context(train_x: np.ndarray, current_x: np.ndarray) -> np.ndarray:
    """Build row-level PIT-safe routing context.

    Context is derived only from data available at prediction time and the
    historical training window. No target, future result, or current-match
    outcome is used. Each current row receives its own missingness/shift
    features rather than one aggregate context repeated across a fold.
    """
    tr = np.asarray(train_x, dtype=float)
    cu = np.asarray(current_x, dtype=float)
    if cu.ndim == 1:
        cu = cu.reshape(1, -1)
    tr_med = np.nanmedian(tr, axis=0) if tr.size else np.zeros(cu.shape[1])
    tr_med = np.where(np.isfinite(tr_med), tr_med, 0.0)
    tr_scale = np.nanmedian(np.abs(tr - tr_med), axis=0) if tr.size else np.ones(cu.shape[1])
    tr_scale = np.where(np.isfinite(tr_scale) & (tr_scale > 1e-9), tr_scale, 1.0)
    row_miss = np.isnan(cu).mean(axis=1) if cu.size else np.ones(len(cu))
    train_miss = float(np.isnan(tr).mean()) if tr.size else 1.0
    z = np.abs(np.nan_to_num(cu, nan=tr_med) - tr_med) / tr_scale
    z = np.where(np.isfinite(z), z, 0.0)
    row_shift = np.nanmedian(z, axis=1) if z.size else np.zeros(len(cu))
    row_shift = np.where(np.isfinite(row_shift), row_shift, 0.0)
    # Additional regime/context signals are row-local and PIT-safe. They let the
    # router react to unusual feature magnitude, cross-feature disagreement, and
    # the stability of the historical training window without using any target.
    row_abs_z = np.nanmean(z, axis=1) if z.size else np.zeros(len(cu))
    row_abs_z = np.where(np.isfinite(row_abs_z), row_abs_z, 0.0)
    row_dispersion = np.nanstd(np.nan_to_num(cu, nan=tr_med), axis=1) if cu.size else np.zeros(len(cu))
    row_dispersion = np.where(np.isfinite(row_dispersion), row_dispersion, 0.0)
    train_feature_std = np.nanmedian(np.nanstd(tr, axis=0)) if tr.size else 0.0
    train_feature_std = float(train_feature_std) if np.isfinite(train_feature_std) else 0.0
    # Recent-vs-long-history regime signals: all are computed from data available
    # before the current fold/row and therefore remain PIT-safe.
    recent_n = min(120, len(tr))
    recent = tr[-recent_n:] if recent_n else tr
    recent_med = np.nanmedian(recent, axis=0) if recent.size else tr_med
    recent_med = np.where(np.isfinite(recent_med), recent_med, tr_med)
    regime_z = np.abs(recent_med - tr_med) / tr_scale
    regime_shift = float(np.nanmedian(regime_z)) if regime_z.size else 0.0
    recent_std = np.nanmedian(np.nanstd(recent, axis=0)) if recent.size else train_feature_std
    recent_std = float(recent_std) if np.isfinite(recent_std) else train_feature_std
    recent_z = np.abs(np.nan_to_num(cu, nan=recent_med) - recent_med) / tr_scale
    recent_z = np.where(np.isfinite(recent_z), recent_z, 0.0)
    row_recent_shift = np.nanmedian(recent_z, axis=1) if recent_z.size else np.zeros(len(cu))
    row_recent_shift = np.where(np.isfinite(row_recent_shift), row_recent_shift, 0.0)
    train_size = np.log1p(len(tr))
    return np.column_stack([
        np.full(len(cu), train_size, dtype=float),
        np.full(len(cu), train_miss, dtype=float),
        row_miss.astype(float),
        row_shift.astype(float),
        row_abs_z.astype(float),
        row_dispersion.astype(float),
        np.full(len(cu), train_feature_std, dtype=float),
        np.full(len(cu), regime_shift, dtype=float),
        row_recent_shift.astype(float),
        np.full(len(cu), recent_std, dtype=float),
    ])



def _recent_model_loss(meta_losses: Sequence[Sequence[float]], n_models: int) -> np.ndarray:
    """Recent OOF log-loss state using only rows observed before the current fold."""
    if not meta_losses:
        return np.full(n_models, np.log(2.0), dtype=float)
    arr=np.asarray(meta_losses[-180:],dtype=float)
    if arr.ndim!=2 or arr.shape[1]!=n_models:
        return np.full(n_models, np.log(2.0), dtype=float)
    w=np.exp(np.linspace(-1.0,0.0,len(arr)))
    out=np.average(arr,axis=0,weights=w)
    return np.where(np.isfinite(out),out,np.log(2.0))


def _fit_contextual_loss_selector(meta_features: np.ndarray, meta_losses: np.ndarray):
    """Fit one PIT-safe loss forecaster per base model using only prior OOF rows."""
    X = np.asarray(meta_features, dtype=float)
    L = np.asarray(meta_losses, dtype=float)
    if X.ndim != 2 or L.ndim != 2 or len(X) < 120 or len(X) != len(L):
        return None
    selectors = []
    for j in range(L.shape[1]):
        model = HistGradientBoostingRegressor(
            max_iter=120,
            learning_rate=0.04,
            max_leaf_nodes=7,
            min_samples_leaf=20,
            l2_regularization=2.0,
            random_state=42 + j,
        )
        model.fit(X, L[:, j])
        selectors.append(model)
    return {"kind": "contextual_loss_v1", "selectors": selectors}


def _route_with_contextual_loss_selector(selector, bp: np.ndarray, ctx: np.ndarray, history_loss=None):
    """Convert predicted per-model loss into conservative situation-specific weights."""
    if not isinstance(selector, dict) or selector.get("kind") != "contextual_loss_v1":
        return None
    selectors = selector.get("selectors") or []
    if not selectors:
        return None
    hl = np.asarray(history_loss if history_loss is not None else selector.get('history_loss'), dtype=float)
    if hl.ndim != 1 or len(hl) != bp.shape[1]:
        hl = np.full(bp.shape[1], np.log(2.0), dtype=float)
    features = np.column_stack([bp, ctx, np.std(bp, axis=1), np.repeat(hl[None, :], len(bp), axis=0)])
    predicted = np.column_stack([m.predict(features) for m in selectors])
    predicted = np.where(np.isfinite(predicted), predicted, np.nanmedian(predicted, axis=0))
    baseline = np.mean(bp, axis=1)
    # Lower predicted log-loss => larger weight. Temperature prevents brittle winner-take-all routing.
    centered = predicted - np.min(predicted, axis=1, keepdims=True)
    weights = np.exp(-centered / 0.15)
    weights /= np.maximum(weights.sum(axis=1, keepdims=True), 1e-12)
    # Conservative shrinkage toward equal weighting reduces regime overreaction.
    weights = 0.75 * weights + 0.25 / bp.shape[1]
    routed = np.sum(bp * weights, axis=1)
    return np.clip(0.75 * routed + 0.25 * baseline, 1e-6, 1 - 1e-6)



class DynamicModelRouter:
    """Stateful wrapper for the leakage-safe challenger router."""
    def __init__(self, names: Sequence[str], pool_factory):
        self.names = tuple(names)
        self.pool_factory = pool_factory
        self.router = None
        self.status = "UNFIT"

    def fit(self, X, y, sel, start, step):
        y_arr = np.asarray(y)
        if len(np.unique(y_arr)) != 2:
            self.router = None
            self.status = "UNSUPPORTED_MULTICLASS_RESEARCH_ONLY"
            return self
        self.router = fit_final_router(
            X, y_arr, self.names, sel, start, step, self.pool_factory
        )
        self.status = "FIT" if self.router is not None else "INSUFFICIENT_OOS"
        return self

    def predict(self, base_models, train_x, current_x):
        return predict_with_router(
            self.router, base_models, self.names, train_x, current_x
        )

def _require_binary_target(y):
    return len(np.unique(np.asarray(y))) == 2


def evaluate_router(
    X: np.ndarray,
    y: np.ndarray,
    names: Sequence[str],
    sel: int,
    start: int,
    step: int,
    pool_factory,
    metric=None,
) -> Dict:
    """Nested chronological OOS comparison with a contextual loss router."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y)
    if not _require_binary_target(y):
        return {"status": "UNSUPPORTED_MULTICLASS_RESEARCH_ONLY", "reason": "router_is_binary_only"}
    if sel <= start + step or len(names) < 2:
        return {"status": "INSUFFICIENT_OOS", "reason": "too_few_chronological_folds"}

    meta_X = []
    meta_losses = []
    static_pred = []
    router_pred = []
    used_folds = 0

    for end in range(start, sel, step):
        te = min(end + step, sel)
        if te <= end or len(np.unique(y[:end])) < 2:
            continue
        base_pred = []
        for name in names:
            model = pool_factory()[name]
            model.fit(X[:end], y[:end])
            base_pred.append(np.clip(model.predict_proba(X[end:te])[:, 1], 1e-6, 1 - 1e-6))
        bp = np.column_stack(base_pred)
        static = bp.mean(axis=1)
        ctx = _context(X[:end], X[end:te])
        history_loss=_recent_model_loss(meta_losses,len(names))
        features = np.column_stack([bp, ctx, np.std(bp, axis=1), np.repeat(history_loss[None,:], len(bp), axis=0)])

        selector = _fit_contextual_loss_selector(
            np.asarray(meta_X, dtype=float) if meta_X else np.empty((0, features.shape[1])),
            np.asarray(meta_losses, dtype=float) if meta_losses else np.empty((0, len(names))),
        )
        routed = _route_with_contextual_loss_selector(selector, bp, ctx, history_loss)
        if routed is None:
            routed = static.copy()

        static_pred.extend(static.tolist())
        router_pred.extend(routed.tolist())

        yt = y[end:te].astype(float)
        fold_losses = -(
            yt[:, None] * np.log(bp)
            + (1.0 - yt[:, None]) * np.log(1.0 - bp)
        )
        meta_X.extend(features.tolist())
        meta_losses.extend(fold_losses.tolist())
        used_folds += 1

    if len(meta_losses) < 120:
        return {
            "status": "INSUFFICIENT_OOS",
            "reason": "insufficient_router_training_oof",
            "oos_rows": len(meta_losses),
        }

    static_m = _metric(y[start:sel], static_pred)
    router_m = _metric(y[start:sel], router_pred)
    return {
        "status": "EVALUATED",
        "folds": used_folds,
        "oos_rows": len(meta_losses),
        "fixed_ensemble": static_m,
        "dynamic_router": router_m,
        "logloss_improvement": static_m["logloss"] - router_m["logloss"],
        "brier_improvement": static_m["brier"] - router_m["brier"],
        "ece_change": router_m["ece"] - static_m["ece"],
        "policy": "challenger_only; chronological OOF; contextual per-model loss forecasting; frozen holdout untouched",
    }

def evaluate_frozen_holdout_router(
    X: np.ndarray,
    y: np.ndarray,
    names: Sequence[str],
    sel: int,
    start: int,
    step: int,
    pool_factory,
    metric=None,
) -> Dict:
    """Evaluate a contextual loss router fit only on pre-holdout OOF rows."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y)
    if not _require_binary_target(y):
        return {"status": "UNSUPPORTED_MULTICLASS_RESEARCH_ONLY", "reason": "router_is_binary_only"}
    if sel <= start or sel >= len(y) or len(names) < 2:
        return {"status": "INSUFFICIENT_HOLDOUT", "reason": "invalid_frozen_holdout_split"}

    meta_X = []
    meta_losses = []
    for end in range(start, sel, step):
        te = min(end + step, sel)
        if te <= end or len(np.unique(y[:end])) < 2:
            continue
        bp = []
        for name in names:
            model = pool_factory()[name]
            model.fit(X[:end], y[:end])
            bp.append(np.clip(model.predict_proba(X[end:te])[:, 1], 1e-6, 1 - 1e-6))
        bp = np.column_stack(bp)
        ctx = _context(X[:end], X[end:te])
        history_loss=_recent_model_loss(meta_losses,len(names))
        features = np.column_stack([bp, ctx, np.std(bp, axis=1), np.repeat(history_loss[None,:], len(bp), axis=0)])
        yt = y[end:te].astype(float)
        fold_losses = -(
            yt[:, None] * np.log(bp)
            + (1.0 - yt[:, None]) * np.log(1.0 - bp)
        )
        meta_X.extend(features.tolist())
        meta_losses.extend(fold_losses.tolist())

    selector = _fit_contextual_loss_selector(np.asarray(meta_X, dtype=float), np.asarray(meta_losses, dtype=float))
    if selector is None:
        return {"status": "INSUFFICIENT_OOS", "reason": "insufficient_router_training_oof", "oos_rows": len(meta_losses)}

    bp = []
    for name in names:
        model = pool_factory()[name]
        model.fit(X[:sel], y[:sel])
        bp.append(np.clip(model.predict_proba(X[sel:])[:, 1], 1e-6, 1 - 1e-6))
    bp = np.column_stack(bp)
    static = bp.mean(axis=1)
    ctx = _context(X[:sel], X[sel:])
    routed = _route_with_contextual_loss_selector(selector, bp, ctx, _recent_model_loss(meta_losses,len(names)))
    if routed is None:
        return {"status": "INSUFFICIENT_OOS", "reason": "contextual_router_fit_failed", "oos_rows": len(meta_losses)}

    target = y[sel:]
    static_m = _metric(target, static)
    routed_m = _metric(target, routed)
    return {
        "status": "EVALUATED",
        "oos_training_rows": len(meta_losses),
        "holdout_rows": len(target),
        "fixed_ensemble": static_m,
        "dynamic_router": routed_m,
        "logloss_improvement": static_m["logloss"] - routed_m["logloss"],
        "brier_improvement": static_m["brier"] - routed_m["brier"],
        "ece_change": routed_m["ece"] - static_m["ece"],
        "policy": "router_fit_pre_holdout_only; per-model OOF loss targets; frozen_holdout_labels_used_only_for_scoring",
    }

def fit_final_router(X, y, names, sel, start, step, pool_factory):
    """Fit the final contextual loss router from pre-holdout chronological OOF."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y)
    if not _require_binary_target(y):
        return None
    meta_X = []
    meta_losses = []
    for end in range(start, sel, step):
        te = min(end + step, sel)
        if te <= end or len(np.unique(y[:end])) < 2:
            continue
        bp = []
        for name in names:
            model = pool_factory()[name]
            model.fit(X[:end], y[:end])
            bp.append(np.clip(model.predict_proba(X[end:te])[:, 1], 1e-6, 1 - 1e-6))
        bp = np.column_stack(bp)
        ctx = _context(X[:end], X[end:te])
        history_loss=_recent_model_loss(meta_losses,len(names))
        features = np.column_stack([bp, ctx, np.std(bp, axis=1), np.repeat(history_loss[None,:], len(bp), axis=0)])
        yt = y[end:te].astype(float)
        fold_losses = -(
            yt[:, None] * np.log(bp)
            + (1.0 - yt[:, None]) * np.log(1.0 - bp)
        )
        meta_X.extend(features.tolist())
        meta_losses.extend(fold_losses.tolist())
    selector=_fit_contextual_loss_selector(
        np.asarray(meta_X, dtype=float),
        np.asarray(meta_losses, dtype=float),
    )
    if selector is not None:
        selector['history_loss']=_recent_model_loss(meta_losses,len(names))
    return selector

def predict_with_router(router, base_models, names, train_x, current_x):
    bp = []
    for name, model in zip(names, base_models):
        proba = np.asarray(model.predict_proba(current_x))
        if proba.ndim != 2 or proba.shape[1] != 2:
            static = np.full(len(current_x), 0.5, dtype=float)
            return static, {"fallback": True, "reason": "multiclass_base_model_unsupported"}
        bp.append(np.clip(proba[:, 1], 1e-6, 1 - 1e-6))
    bp = np.column_stack(bp)
    static = bp.mean(axis=1)
    if router is None:
        return static, {"fallback": True, "reason": "router_unavailable"}
    ctx = _context(train_x, current_x)
    routed = _route_with_contextual_loss_selector(router, bp, ctx)
    if routed is None:
        return static, {"fallback": True, "reason": "contextual_router_unavailable"}
    return routed, {"fallback": False, "router_kind": "contextual_loss_v1", "shrinkage": 0.25}


__all__ = ["DynamicModelRouter", "evaluate_router", "fit_final_router", "predict_with_router"]
