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
    """PIT-safe context: only feature availability/distribution and sample size."""
    tr = np.asarray(train_x, dtype=float)
    cu = np.asarray(current_x, dtype=float)
    tr_med = np.nanmedian(tr, axis=0)
    tr_med = np.where(np.isfinite(tr_med), tr_med, 0.0)
    tr_scale = np.nanmedian(np.abs(tr - tr_med), axis=0)
    tr_scale = np.where(np.isfinite(tr_scale) & (tr_scale > 1e-9), tr_scale, 1.0)
    miss = float(np.isnan(cu).mean()) if cu.size else 1.0
    train_miss = float(np.isnan(tr).mean()) if tr.size else 1.0
    shift = np.nanmedian(np.abs(np.nanmedian(cu, axis=0) - tr_med) / tr_scale) if cu.size else 0.0
    if not np.isfinite(shift):
        shift = 0.0
    disagreement = 0.0
    return np.array([
        np.log1p(len(tr)),
        train_miss,
        miss,
        float(shift),
        disagreement,
    ], dtype=float)


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
        ctx_block = np.repeat(ctx.reshape(1, -1), te - end, axis=0)
        features = np.column_stack([bp, ctx_block])

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
        ctx = np.repeat(_context(X[:end], X[end:te]).reshape(1, -1), te - end, axis=0)
        meta_X.extend(np.column_stack([bp, ctx]).tolist())
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
        bp.append(np.clip(model.predict_proba(current_x)[:, 1], 1e-6, 1 - 1e-6))
    bp = np.column_stack(bp)
    static = bp.mean(axis=1)
    if router is None:
        return static, {"fallback": True, "reason": "router_unavailable"}
    ctx = np.repeat(_context(train_x, current_x).reshape(1, -1), len(current_x), axis=0)
    rp = np.clip(router.predict_proba(np.column_stack([bp, ctx]))[:, 1], 1e-6, 1 - 1e-6)
    # Fail-safe: extreme routing output is shrunk toward the incumbent blend.
    rp = 0.75 * rp + 0.25 * static
    return rp, {"fallback": False, "shrinkage": 0.25}
