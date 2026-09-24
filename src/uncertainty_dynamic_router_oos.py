from __future__ import annotations

"""
Research-only uncertainty-aware dynamic routing.

Extends the existing contextual loss router without changing the production
incumbent. The selector is trained only on chronological OOF information.
"""

from typing import Dict, Sequence
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression

EPS = 1e-6


def _clip_prob(p):
    return np.clip(np.asarray(p, dtype=float), EPS, 1.0 - EPS)


def predictive_entropy(p):
    p = _clip_prob(p)
    return -(p * np.log(p) + (1.0 - p) * np.log(1.0 - p))


def uncertainty_features(base_probs: np.ndarray, context: np.ndarray) -> np.ndarray:
    """
    Row-local uncertainty/drift features.

    Columns:
      0 ensemble mean probability
      1 expert disagreement proxy
      2 predictive entropy
      3 mean expert entropy
      4 mutual-information proxy
      5 max pairwise probability gap
      6 confidence distance from 0.5
      7 row shift
      8 recent row shift
      9 combined drift score
    """
    bp = _clip_prob(base_probs)
    if bp.ndim != 2 or bp.shape[1] < 2:
        raise ValueError("base_probs must be 2D with at least two experts")
    ctx = np.asarray(context, dtype=float)
    if ctx.ndim != 2 or len(ctx) != len(bp):
        raise ValueError("context must be 2D with matching rows")

    mean_p = np.mean(bp, axis=1)
    disagreement = np.std(bp, axis=1)
    pred_ent = predictive_entropy(mean_p)
    mean_ent = np.mean(predictive_entropy(bp), axis=1)
    mi = np.maximum(pred_ent - mean_ent, 0.0)
    pair_gap = np.max(bp, axis=1) - np.min(bp, axis=1)
    confidence = np.abs(mean_p - 0.5)

    row_shift = ctx[:, 3] if ctx.shape[1] > 3 else np.zeros(len(bp))
    recent_shift = ctx[:, 8] if ctx.shape[1] > 8 else row_shift
    row_missing = ctx[:, 2] if ctx.shape[1] > 2 else np.zeros(len(bp))
    drift = np.clip(
        0.50 * np.clip(row_shift, 0.0, 8.0) / 8.0
        + 0.35 * np.clip(recent_shift, 0.0, 8.0) / 8.0
        + 0.15 * np.clip(row_missing, 0.0, 1.0),
        0.0,
        1.0,
    )

    return np.column_stack([
        mean_p, disagreement, pred_ent, mean_ent, mi,
        pair_gap, confidence, row_shift, recent_shift, drift,
    ])


def route_uncertainty_score(
    predicted_loss: np.ndarray,
    base_probs: np.ndarray,
    context: np.ndarray,
    baseline: np.ndarray | None = None,
):
    """
    Conservative fusion.

    Uncertainty alone does not increase routing. Routing strength grows only
    when predicted expert losses are separated enough to imply recoverable risk.
    High disagreement or drift therefore causes additional shrinkage unless a
    specialist is clearly better in the current context.
    """
    loss = np.asarray(predicted_loss, dtype=float)
    bp = _clip_prob(base_probs)
    if loss.ndim != 2 or loss.shape != bp.shape:
        raise ValueError("predicted_loss/base_probs shape mismatch")
    if bp.shape[1] < 2:
        return np.mean(bp, axis=1)

    if baseline is None:
        baseline = np.mean(bp, axis=1)
    else:
        baseline = _clip_prob(baseline)

    centered = loss - np.min(loss, axis=1, keepdims=True)
    weights = np.exp(-centered / 0.15)
    weights /= np.maximum(weights.sum(axis=1, keepdims=True), EPS)

    uf = uncertainty_features(bp, context)
    uncertainty = np.clip(
        0.45 * uf[:, 1] / 0.20
        + 0.25 * uf[:, 4] / 0.08
        + 0.30 * uf[:, 9],
        0.0,
        1.0,
    )

    spread = np.max(loss, axis=1) - np.min(loss, axis=1)
    recoverability = spread / np.maximum(spread + 0.05, EPS)
    route_strength = 0.75 * recoverability * (1.0 - 0.60 * uncertainty)
    route_strength *= (1.0 - 0.35 * uf[:, 9])
    route_strength = np.clip(route_strength, 0.0, 0.75)

    routed = np.sum(bp * weights, axis=1)
    return np.clip(
        baseline + route_strength * (routed - baseline),
        EPS,
        1.0 - EPS,
    )


def _history_loss(meta_losses, n_models):
    if not meta_losses:
        return np.full(n_models, np.log(2.0), dtype=float)
    arr = np.asarray(meta_losses[-180:], dtype=float)
    if arr.ndim != 2 or arr.shape[1] != n_models:
        return np.full(n_models, np.log(2.0), dtype=float)
    w = np.exp(np.linspace(-1.0, 0.0, len(arr)))
    out = np.average(arr, axis=0, weights=w)
    return np.where(np.isfinite(out), out, np.log(2.0))


def fit_uncertainty_loss_selector(
    meta_features: np.ndarray,
    meta_losses: np.ndarray,
    model_names: Sequence[str],
):
    X = np.asarray(meta_features, dtype=float)
    L = np.asarray(meta_losses, dtype=float)
    if X.ndim != 2 or L.ndim != 2 or len(X) < 120 or len(X) != len(L):
        return None
    if L.shape[1] != len(model_names):
        return None

    selectors = []
    for j in range(L.shape[1]):
        m = HistGradientBoostingRegressor(
            max_iter=120,
            learning_rate=0.04,
            max_leaf_nodes=7,
            min_samples_leaf=20,
            l2_regularization=2.0,
            random_state=1042 + j,
        )
        m.fit(X, L[:, j])
        selectors.append(m)

    return {
        "kind": "uncertainty_loss_v2",
        "model_names": list(model_names),
        "selectors": selectors,
    }


def _fold_context(X, end, te):
    from src import dynamic_model_router as existing
    return existing._context(X[:end], X[end:te])


def evaluate_oof(
    X: np.ndarray,
    y: np.ndarray,
    names: Sequence[str],
    folds: Sequence[Dict],
    baseline_weights: Dict[str, float] | None = None,
    metric_fn=None,
):
    """
    Chronological OOF evaluation against the exact incumbent baseline.
    No holdout labels are used.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    if metric_fn is None:
        from src.research_cycle_v4 import metric as metric_fn

    meta_x, meta_l = [], []
    static_all, routed_all, y_all = [], [], []
    fold_deltas = []

    for fold in folds:
        end = int(fold["end"])
        te = int(fold["te"])
        bp = np.column_stack([
            _clip_prob(np.asarray(fold["preds"][n], dtype=float))
            for n in names
        ])
        ctx = _fold_context(X, end, te)
        history = _history_loss(meta_l, len(names))
        uf = uncertainty_features(bp, ctx)
        features = np.column_stack([
            bp,
            ctx,
            np.std(bp, axis=1),
            uf,
            np.repeat(history[None, :], len(bp), axis=0),
        ])

        selector = fit_uncertainty_loss_selector(
            np.asarray(meta_x, dtype=float)
            if meta_x else np.empty((0, features.shape[1])),
            np.asarray(meta_l, dtype=float)
            if meta_l else np.empty((0, len(names))),
            names,
        )

        if baseline_weights:
            w = np.asarray([float(baseline_weights.get(n, 0.0)) for n in names])
            if np.isfinite(w).all() and w.sum() > 0:
                w /= w.sum()
                static = np.sum(bp * w[None, :], axis=1)
            else:
                static = np.mean(bp, axis=1)
        else:
            static = np.mean(bp, axis=1)

        if selector is None:
            routed = static.copy()
        else:
            pred_l = np.column_stack([
                m.predict(features) for m in selector["selectors"]
            ])
            pred_l = np.where(np.isfinite(pred_l), pred_l, np.log(2.0))
            routed = route_uncertainty_score(
                pred_l, bp, ctx, baseline=static
            )

        static_all.extend(static.tolist())
        routed_all.extend(routed.tolist())
        y_all.extend(y[end:te].tolist())

        yt = y[end:te].astype(float)
        losses = -(
            yt[:, None] * np.log(bp)
            + (1.0 - yt[:, None]) * np.log(1.0 - bp)
        )
        meta_x.extend(features.tolist())
        meta_l.extend(losses.tolist())

        if len(yt) and len(np.unique(yt)) > 1:
            fold_deltas.append(float(
                metric_fn(yt, routed)["logloss"]
                - metric_fn(yt, static)["logloss"]
            ))

    if len(meta_l) < 120:
        return {
            "status": "INSUFFICIENT_OOS",
            "oos_rows": len(meta_l),
        }

    static_m = metric_fn(np.asarray(y_all), np.asarray(static_all))
    routed_m = metric_fn(np.asarray(y_all), np.asarray(routed_all))
    return {
        "status": "EVALUATED",
        "oos_rows": len(meta_l),
        "folds": len(fold_deltas),
        "fixed_ensemble": static_m,
        "uncertainty_router": routed_m,
        "logloss_improvement": static_m["logloss"] - routed_m["logloss"],
        "brier_improvement": static_m["brier"] - routed_m["brier"],
        "ece_change": routed_m["ece"] - static_m["ece"],
        "fold_logloss_deltas": [float(x) for x in fold_deltas],
        "policy": "research_only; chronological OOF; uncertainty_disagreement_drift; no holdout fitting",
    }


def temporal_recalibration(p, y):
    """
    Fit a low-capacity calibrator only on pre-holdout sequential data.
    """
    p = _clip_prob(p)
    y = np.asarray(y, dtype=int)
    n = len(p)
    if n < 180 or len(np.unique(y)) < 2:
        return {
            "accepted": False,
            "method": "none",
            "reason": "insufficient_preholdout_oof",
        }

    cuts = sorted(set([
        max(80, int(n * 0.50)),
        max(110, int(n * 0.67)),
        max(140, int(n * 0.80)),
    ]))
    cuts = [c for c in cuts if c < n - 30]
    if len(cuts) < 2:
        return {
            "accepted": False,
            "method": "none",
            "reason": "insufficient_temporal_folds",
        }

    def fit_predict(method, train_p, train_y, test_p):
        train_p = _clip_prob(train_p)
        test_p = _clip_prob(test_p)
        z = np.log(train_p / (1.0 - train_p))
        zt = np.log(test_p / (1.0 - test_p))
        if method == "none":
            return test_p, None
        if method == "sigmoid":
            m = LogisticRegression(C=0.25, max_iter=2000, random_state=1202)
            m.fit(z.reshape(-1, 1), train_y)
            return _clip_prob(m.predict_proba(zt.reshape(-1, 1))[:, 1]), m
        if method == "beta":
            m = LogisticRegression(C=0.25, max_iter=2000, random_state=1203)
            a = np.column_stack([np.log(train_p), np.log(1.0 - train_p)])
            at = np.column_stack([np.log(test_p), np.log(1.0 - test_p)])
            m.fit(a, train_y)
            return _clip_prob(m.predict_proba(at)[:, 1]), m
        if method == "isotonic":
            if len(train_p) < 120 or len(np.unique(train_p)) < 25:
                return None, None
            m = IsotonicRegression(
                y_min=EPS, y_max=1.0-EPS, out_of_bounds="clip"
            )
            m.fit(train_p, train_y)
            return _clip_prob(m.predict(test_p)), m
        raise ValueError(method)

    from src.research_cycle_v4 import metric
    methods = ["none", "sigmoid", "beta", "isotonic"]
    scores = {m: [] for m in methods}
    bounds = list(zip(cuts, cuts[1:] + [n]))

    for method in methods:
        for a, b in bounds:
            pp, _ = fit_predict(method, p[:a], y[:a], p[a:b])
            if pp is None:
                continue
            scores[method].append(metric(y[a:b], pp))

    raw = scores["none"]
    if len(raw) < 2:
        return {
            "accepted": False,
            "method": "none",
            "reason": "raw_validation_unavailable",
        }

    def objective(items):
        ll = np.asarray([m["logloss"] for m in items], dtype=float)
        return float(np.mean(ll) + 0.05 * np.std(ll))

    candidates = {
        m: v for m, v in scores.items()
        if m == "none" or len(v) >= 2
    }
    method = min(
        candidates,
        key=lambda m: (
            objective(candidates[m]),
            np.mean([z["brier"] for z in candidates[m]]),
        ),
    )
    raw_obj = objective(candidates["none"])
    cand_obj = objective(candidates[method])
    raw_brier = float(np.mean([z["brier"] for z in candidates["none"]]))
    cand_brier = float(np.mean([z["brier"] for z in candidates[method]]))
    accepted = (
        method != "none"
        and cand_obj <= raw_obj - max(0.001, 0.003 * raw_obj)
        and cand_brier <= raw_brier + 0.002
    )
    if not accepted:
        return {
            "accepted": False,
            "method": "none",
            "reason": "recalibration_did_not_pass_temporal_gate",
            "candidate_methods": candidates,
        }

    if method == "sigmoid":
        final = LogisticRegression(C=0.25, max_iter=2000, random_state=1202)
        z = np.log(p / (1.0 - p)).reshape(-1, 1)
        final.fit(z, y)
    elif method == "beta":
        final = LogisticRegression(C=0.25, max_iter=2000, random_state=1203)
        final.fit(
            np.column_stack([np.log(p), np.log(1.0 - p)]),
            y,
        )
    else:
        final = IsotonicRegression(
            y_min=EPS, y_max=1.0-EPS, out_of_bounds="clip"
        )
        final.fit(p, y)

    return {
        "accepted": True,
        "method": method,
        "model": final,
        "candidate_methods": candidates,
    }


__all__ = [
    "predictive_entropy",
    "uncertainty_features",
    "route_uncertainty_score",
    "fit_uncertainty_loss_selector",
    "evaluate_oof",
    "temporal_recalibration",
]
