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
    train_size = np.log1p(len(tr))
    return np.column_stack([
        np.full(len(cu), train_size, dtype=float),
        np.full(len(cu), train_miss, dtype=float),
        row_miss.astype(float),
        row_shift.astype(float),
        row_abs_z.astype(float),
        row_dispersion.astype(float),
        np.full(len(cu), train_feature_std, dtype=float),
    ])



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
    metric= None,
) -> Dict:
    """Nested chronological OOS comparison of fixed blend vs dynamic router.

    Base models are refit for every chronological fold. The meta-model is fit
    only on earlier OOS folds, never on the current fold. This prevents the
    router from learning from the target it is being evaluated on.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y)
    if not _require_binary_target(y):
        return {"status": "UNSUPPORTED_MULTICLASS_RESEARCH_ONLY", "reason": "router_is_binary_only"}
    if sel <= start + step or len(names) < 2:
        return {"status": "INSUFFICIENT_OOS", "reason": "too_few_chronological_folds"}

    meta_X: List[np.ndarray] = []
    meta_y: List[int] = []
    static_pred: List[float] = []
    router_pred: List[float] = []
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
        features = np.column_stack([bp, ctx, np.std(bp, axis=1)])

        # A router must have enough prior OOF observations. Before that point,
        # fail safely to the incumbent fixed blend.
        if len(meta_y) >= 60 and len(np.unique(meta_y)) == 2:
            router = Pipeline([
                ("scale", StandardScaler()),
                ("model", LogisticRegression(C=0.25, max_iter=2000, random_state=42)),
            ])
            router.fit(np.asarray(meta_X), np.asarray(meta_y))
            rp = np.clip(router.predict_proba(features)[:, 1], 1e-6, 1 - 1e-6)
        else:
            rp = static.copy()

        static_pred.extend(static.tolist())
        router_pred.extend(rp.tolist())
        meta_X.extend(features.tolist())
        meta_y.extend(y[end:te].tolist())
        used_folds += 1

    if len(meta_y) < 60 or len(np.unique(meta_y)) < 2:
        return {"status": "INSUFFICIENT_OOS", "reason": "insufficient_router_training_oof", "oos_rows": len(meta_y)}

    static_m = _metric(meta_y, static_pred)
    router_m = _metric(meta_y, router_pred)
    return {
        "status": "EVALUATED",
        "folds": used_folds,
        "oos_rows": len(meta_y),
        "fixed_ensemble": static_m,
        "dynamic_router": router_m,
        "logloss_improvement": static_m["logloss"] - router_m["logloss"],
        "brier_improvement": static_m["brier"] - router_m["brier"],
        "ece_change": router_m["ece"] - static_m["ece"],
        "policy": "challenger_only; chronological OOF; frozen holdout untouched",
    }


def fit_final_router(X, y, names, sel, start, step, pool_factory):
    """Fit the final router from all pre-holdout chronological OOF predictions."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y)
    if not _require_binary_target(y):
        return None
    meta_X, meta_y = [], []
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
        meta_X.extend(np.column_stack([bp, ctx, np.std(bp, axis=1)]).tolist())
        meta_y.extend(y[end:te].tolist())
    if len(meta_y) < 60 or len(np.unique(meta_y)) < 2:
        return None
    router = Pipeline([
        ("scale", StandardScaler()),
        ("model", LogisticRegression(C=0.25, max_iter=2000, random_state=42)),
    ])
    router.fit(np.asarray(meta_X), np.asarray(meta_y))
    return router


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
    rp = np.clip(router.predict_proba(np.column_stack([bp, ctx, np.std(bp, axis=1)]))[:, 1], 1e-6, 1 - 1e-6)
    # Fail-safe: extreme routing output is shrunk toward the incumbent blend.
    rp = 0.75 * rp + 0.25 * static
    return rp, {"fallback": False, "shrinkage": 0.25}


__all__ = ["DynamicModelRouter", "evaluate_router", "fit_final_router", "predict_with_router"]
