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


def population_drift_features(reference: np.ndarray, current: np.ndarray) -> np.ndarray:
    """Compute bounded population drift state from prediction-time covariates.

    The state is outcome-free. It combines robust location shift, missingness
    shift, and a bounded RBF-MMD estimate. The deterministic row cap keeps the
    research path inexpensive and reproducible.
    """
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    if ref.ndim != 2 or cur.ndim != 2 or ref.shape[1] != cur.shape[1]:
        raise ValueError("reference/current feature shape mismatch")
    if len(ref) == 0 or len(cur) == 0 or ref.shape[1] == 0:
        return np.zeros(3, dtype=float)

    ref_med = np.nanmedian(ref, axis=0)
    q75 = np.nanpercentile(ref, 75.0, axis=0)
    q25 = np.nanpercentile(ref, 25.0, axis=0)
    ref_med = np.where(np.isfinite(ref_med), ref_med, 0.0)
    q75 = np.where(np.isfinite(q75), q75, ref_med + 0.5)
    q25 = np.where(np.isfinite(q25), q25, ref_med - 0.5)
    scale = np.maximum(q75 - q25, 1e-6)
    cur_med = np.nanmedian(cur, axis=0)
    cur_med = np.where(np.isfinite(cur_med), cur_med, ref_med)
    robust_shift = np.nanmean(np.minimum(np.abs(cur_med - ref_med) / scale, 5.0) / 5.0)
    missing_shift = np.nanmean(
        np.abs(np.mean(np.isfinite(cur), axis=0) - np.mean(np.isfinite(ref), axis=0))
    )
    if not np.isfinite(robust_shift):
        robust_shift = 0.0
    if not np.isfinite(missing_shift):
        missing_shift = 0.0

    def _matrix(x, limit=96):
        if len(x) > limit:
            idx = np.linspace(0, len(x) - 1, limit, dtype=int)
            x = x[idx]
        z = np.where(np.isfinite(x), x, ref_med[None, :])
        z = (z - ref_med[None, :]) / scale[None, :]
        z = np.clip(z, -8.0, 8.0)
        return z

    r = _matrix(ref)
    c = _matrix(cur)
    rr = np.sum((r[:, None, :] - r[None, :, :]) ** 2, axis=2)
    cc = np.sum((c[:, None, :] - c[None, :, :]) ** 2, axis=2)
    rc = np.sum((r[:, None, :] - c[None, :, :]) ** 2, axis=2)
    cross = rc[np.isfinite(rc)]
    bandwidth = float(np.sqrt(np.median(cross[cross > 0.0]))) if np.any(cross > 0.0) else 1.0
    bandwidth = max(bandwidth, 0.25)
    denom = 2.0 * bandwidth * bandwidth
    krr = np.exp(-rr / denom)
    kcc = np.exp(-cc / denom)
    krc = np.exp(-rc / denom)
    mmd2 = float(np.mean(krr) + np.mean(kcc) - 2.0 * np.mean(krc))
    mmd_score = float(np.clip(max(mmd2, 0.0) / (max(mmd2, 0.0) + 0.05), 0.0, 1.0))
    return np.asarray([
        float(np.clip(robust_shift, 0.0, 1.0)),
        float(np.clip(missing_shift, 0.0, 1.0)),
        mmd_score,
    ], dtype=float)


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
    # Context layout: canonical 10 router columns, then 14 matchday
    # columns (10 state + 4 quality), then 3 population-drift columns.
    matchday = ctx[:, 10:24] if ctx.shape[1] > 10 else np.empty((len(bp), 0))
    global_drift = ctx[:, 24:27] if ctx.shape[1] > 24 else np.empty((len(bp), 0))
    if matchday.shape[1] >= 10:
        finite_md = np.isfinite(matchday)
        md_missing = 1.0 - np.mean(finite_md, axis=1)
        bounded_state = np.nan_to_num(matchday[:, :10], nan=0.0, posinf=0.0, neginf=0.0)
        # The first seven fields carry actual late-state movement; counts are
        # normalized and quality metadata is handled separately below.
        md_mag = np.mean(
            np.column_stack([
                np.clip(np.abs(bounded_state[:, 0]), 0.0, 5.0) / 5.0,
                np.clip(np.abs(bounded_state[:, 1]), 0.0, 5.0) / 5.0,
                np.clip(np.abs(bounded_state[:, 2]), 0.0, 5.0) / 5.0,
                np.clip(np.abs(bounded_state[:, 3]), 0.0, 7.0) / 7.0,
                np.clip(np.abs(bounded_state[:, 4]), 0.0, 4.0) / 4.0,
                np.clip(np.abs(bounded_state[:, 5]), 0.0, 4.0) / 4.0,
                np.clip(np.abs(bounded_state[:, 6]), 0.0, 4.0) / 4.0,
                np.clip(np.abs(bounded_state[:, 7]), 0.0, 1.0),
                np.clip(np.abs(bounded_state[:, 8]), 0.0, 5.0) / 5.0,
                np.clip(np.abs(bounded_state[:, 9]), 0.0, 1.0),
            ]),
            axis=1,
        )
        quality = np.nan_to_num(matchday[:, 10:14], nan=np.nan)
        md_quality_missing = np.mean(~np.isfinite(quality), axis=1) if quality.shape[1] else np.ones(len(bp))
        quality = np.nan_to_num(quality, nan=0.0, posinf=0.0, neginf=0.0)
        # Confidence/freshness/diversity raise trust; conflicts lower it.
        md_quality_score = np.clip(
            0.30 * quality[:, 0]
            + 0.30 * quality[:, 2]
            + 0.20 * quality[:, 3]
            + 0.20 * (1.0 - quality[:, 1]),
            0.0,
            1.0,
        )
        matchday_shock = np.clip(
            0.65 * md_mag
            + 0.15 * (1.0 - md_missing)
            + 0.20 * md_quality_score,
            0.0,
            1.0,
        )
    elif matchday.shape[1]:
        matchday_shock = np.zeros(len(bp))
    else:
        matchday_shock = np.zeros(len(bp))

    if global_drift.shape[1] == 3:
        gd = np.nan_to_num(global_drift, nan=0.0, posinf=0.0, neginf=0.0)
        population_shock = np.clip(
            0.55 * gd[:, 0] + 0.20 * gd[:, 1] + 0.25 * gd[:, 2],
            0.0,
            1.0,
        )
    else:
        population_shock = np.zeros(len(bp))

    drift = np.clip(
        0.30 * np.clip(row_shift, 0.0, 8.0) / 8.0
        + 0.20 * np.clip(recent_shift, 0.0, 8.0) / 8.0
        + 0.10 * np.clip(row_missing, 0.0, 1.0)
        + 0.20 * matchday_shock
        + 0.20 * population_shock,
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
    predicted_voi: np.ndarray | None = None,
):
    """
    Conservative uncertainty + VOI fusion.

    The router does not equate uncertainty with useful extra expertise. Loss
    forecasts identify likely strong experts; optional counterfactual VOI
    forecasts identify experts expected to reduce the incumbent's risk when
    consulted. Drift/disagreement only reduce routing strength unless a
    specialist has positive predicted marginal risk reduction.
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
    loss_weights = np.exp(-centered / 0.15)
    loss_weights /= np.maximum(loss_weights.sum(axis=1, keepdims=True), EPS)

    uf = uncertainty_features(bp, context)
    uncertainty = np.clip(
        0.45 * uf[:, 1] / 0.20
        + 0.25 * uf[:, 4] / 0.08
        + 0.30 * uf[:, 9],
        0.0,
        1.0,
    )

    # Counterfactual VOI is the predicted reduction in proper loss from a
    # fixed 35% consultation of one specialist:
    # mixed = 0.65 * incumbent + 0.35 * expert.
    if predicted_voi is not None:
        voi = np.asarray(predicted_voi, dtype=float)
        if voi.shape != bp.shape:
            raise ValueError("predicted_voi/base_probs shape mismatch")
        voi = np.where(np.isfinite(voi), voi, 0.0)
        positive_voi = np.maximum(voi, 0.0)
        positive_values = positive_voi[positive_voi > 0.0]
        voi_scale = max(
            float(np.quantile(positive_values, 0.75)) if len(positive_values) else 0.01,
            0.005,
        )
        voi_weights = np.exp(positive_voi / voi_scale)
        voi_weights /= np.maximum(voi_weights.sum(axis=1, keepdims=True), EPS)
        # Loss suitability remains dominant; VOI only supplies supporting
        # evidence for which expert is worth consulting.
        weights = 0.80 * loss_weights + 0.20 * voi_weights
        max_voi = np.max(positive_voi, axis=1)
        recoverability = max_voi / np.maximum(max_voi + 0.01, EPS)
    else:
        weights = loss_weights
        spread = np.max(loss, axis=1) - np.min(loss, axis=1)
        recoverability = spread / np.maximum(spread + 0.05, EPS)

    weights = 0.75 * weights + 0.25 / bp.shape[1]
    routed = np.sum(bp * weights, axis=1)

    route_strength = 0.75 * recoverability
    route_strength *= (1.0 - 0.60 * uncertainty)
    route_strength *= (1.0 - 0.35 * uf[:, 9])
    route_strength = np.clip(route_strength, 0.0, 0.75)

    return np.clip(
        baseline + route_strength * (routed - baseline),
        EPS,
        1.0 - EPS,
    )


def _bce_loss(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    p = _clip_prob(p)
    y = np.asarray(y, dtype=float)
    return -(y * np.log(p) + (1.0 - y) * np.log(1.0 - p))


def expert_voi_targets(
    base_probs: np.ndarray,
    y: np.ndarray,
    baseline: np.ndarray,
    consultation_weight: float = 0.35,
) -> np.ndarray:
    """Create OOF-only counterfactual marginal-risk labels for each expert."""
    bp = _clip_prob(base_probs)
    baseline = _clip_prob(baseline)
    y = np.asarray(y, dtype=float)
    if bp.ndim != 2 or bp.shape[0] != len(y) or len(baseline) != len(y):
        raise ValueError("VOI target shape mismatch")
    w = float(np.clip(consultation_weight, 0.05, 0.50))
    mixed = (1.0 - w) * baseline[:, None] + w * bp
    return _bce_loss(baseline, y)[:, None] - _bce_loss(mixed, y[:, None])


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
    meta_voi: np.ndarray | None = None,
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

    voi_selectors = None
    if meta_voi is not None:
        V = np.asarray(meta_voi, dtype=float)
        if V.ndim != 2 or V.shape != L.shape or len(V) != len(X):
            return None
        voi_selectors = []
        for j in range(V.shape[1]):
            m = HistGradientBoostingRegressor(
                max_iter=100,
                learning_rate=0.04,
                max_leaf_nodes=7,
                min_samples_leaf=20,
                l2_regularization=2.5,
                random_state=2042 + j,
            )
            m.fit(X, V[:, j])
            voi_selectors.append(m)

    return {
        "kind": "uncertainty_voi_v3" if voi_selectors is not None else "uncertainty_loss_v2",
        "model_names": list(model_names),
        "selectors": selectors,
        "voi_selectors": voi_selectors,
        "consultation_weight": 0.35,
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

    The VOI selector is trained only on previous OOF folds. Each VOI label is
    a counterfactual proper-loss reduction from consulting one expert at a
    fixed weight. Frozen-holdout labels are never exposed to the selector.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    if metric_fn is None:
        from src.research_cycle_v4 import metric as metric_fn

    meta_x, meta_l, meta_v = [], [], []
    static_all, routed_all, y_all = [], [], []
    fold_deltas = []
    fold_voi_means = []

    for fold in folds:
        end = int(fold["end"])
        te = int(fold["te"])
        bp = np.column_stack([
            _clip_prob(np.asarray(fold["preds"][n], dtype=float))
            for n in names
        ])
        ctx = np.asarray(fold.get("context"), dtype=float) if fold.get("context") is not None else _fold_context(X, end, te)
        history = _history_loss(meta_l, len(names))
        uf = uncertainty_features(bp, ctx)
        features = np.column_stack([
            bp,
            ctx,
            np.std(bp, axis=1),
            uf,
            np.repeat(history[None, :], len(bp), axis=0),
        ])

        if baseline_weights:
            w = np.asarray([float(baseline_weights.get(n, 0.0)) for n in names])
            if np.isfinite(w).all() and w.sum() > 0:
                w /= w.sum()
                static = np.sum(bp * w[None, :], axis=1)
            else:
                static = np.mean(bp, axis=1)
        else:
            static = np.mean(bp, axis=1)

        selector = fit_uncertainty_loss_selector(
            np.asarray(meta_x, dtype=float)
            if meta_x else np.empty((0, features.shape[1])),
            np.asarray(meta_l, dtype=float)
            if meta_l else np.empty((0, len(names))),
            names,
            np.asarray(meta_v, dtype=float)
            if meta_v else np.empty((0, len(names))),
        )

        if selector is None:
            routed = static.copy()
        else:
            pred_l = np.column_stack([
                m.predict(features) for m in selector["selectors"]
            ])
            pred_l = np.where(np.isfinite(pred_l), pred_l, np.log(2.0))
            pred_voi = None
            if selector.get("voi_selectors"):
                pred_voi = np.column_stack([
                    m.predict(features) for m in selector["voi_selectors"]
                ])
                pred_voi = np.where(np.isfinite(pred_voi), pred_voi, 0.0)
            routed = route_uncertainty_score(
                pred_l, bp, ctx, baseline=static, predicted_voi=pred_voi
            )

        static_all.extend(static.tolist())
        routed_all.extend(routed.tolist())
        y_all.extend(y[end:te].tolist())

        yt = y[end:te].astype(float)
        losses = _bce_loss(bp, yt[:, None])
        voi_targets = expert_voi_targets(bp, yt, static)
        meta_x.extend(features.tolist())
        meta_l.extend(losses.tolist())
        meta_v.extend(voi_targets.tolist())
        fold_voi_means.append(float(np.mean(np.maximum(voi_targets, 0.0))))

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
    boot = bootstrap_fold_improvement(fold_deltas)
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
        "bootstrap_probability_improvement": boot["probability_improvement"],
        "bootstrap_p05_improvement": boot["p05_improvement"],
        "mean_positive_voi": float(np.mean(fold_voi_means)) if fold_voi_means else 0.0,
        "max_positive_voi": float(np.max(fold_voi_means)) if fold_voi_means else 0.0,
        "routing_policy": "predicted_loss_0.80 + predicted_counterfactual_voi_0.20; uncertainty/drift shrinkage; bounded consultation",
        "oof_targets": [int(x) for x in y_all],
        "oof_static_predictions": [float(x) for x in static_all],
        "oof_routed_predictions": [float(x) for x in routed_all],
        "policy": "research_only; chronological OOF; uncertainty_disagreement_drift; counterfactual_VOI; no holdout fitting",
    }


def fit_final_selector_from_folds(
    X: np.ndarray,
    y: np.ndarray,
    names: Sequence[str],
    folds: Sequence[Dict],
    baseline_weights: Dict[str, float] | None = None,
):
    """Fit the uncertainty+VOI selector on every pre-holdout OOF fold."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    meta_x, meta_l, meta_v = [], [], []
    for fold in folds:
        end = int(fold["end"])
        te = int(fold["te"])
        bp = np.column_stack([
            _clip_prob(np.asarray(fold["preds"][n], dtype=float))
            for n in names
        ])
        ctx = np.asarray(fold.get("context"), dtype=float) if fold.get("context") is not None else _fold_context(X, end, te)
        history = _history_loss(meta_l, len(names))
        uf = uncertainty_features(bp, ctx)
        features = np.column_stack([
            bp,
            ctx,
            np.std(bp, axis=1),
            uf,
            np.repeat(history[None, :], len(bp), axis=0),
        ])
        if baseline_weights:
            w = np.asarray([float(baseline_weights.get(n, 0.0)) for n in names])
            if np.isfinite(w).all() and w.sum() > 0:
                w /= w.sum()
                static = np.sum(bp * w[None, :], axis=1)
            else:
                static = np.mean(bp, axis=1)
        else:
            static = np.mean(bp, axis=1)
        yt = y[end:te].astype(float)
        losses = _bce_loss(bp, yt[:, None])
        voi_targets = expert_voi_targets(bp, yt, static)
        meta_x.extend(features.tolist())
        meta_l.extend(losses.tolist())
        meta_v.extend(voi_targets.tolist())
    selector = fit_uncertainty_loss_selector(
        np.asarray(meta_x, dtype=float),
        np.asarray(meta_l, dtype=float),
        names,
        np.asarray(meta_v, dtype=float),
    )
    return selector, _history_loss(meta_l, len(names)), len(meta_l)


def route_with_selector(
    selector,
    history_loss,
    base_probs: np.ndarray,
    context: np.ndarray,
    baseline: np.ndarray,
):
    """Apply a selector fitted strictly on pre-holdout OOF data."""
    bp = _clip_prob(base_probs)
    ctx = np.asarray(context, dtype=float)
    history = np.asarray(history_loss, dtype=float)
    if selector is None:
        return _clip_prob(baseline)
    uf = uncertainty_features(bp, ctx)
    features = np.column_stack([
        bp,
        ctx,
        np.std(bp, axis=1),
        uf,
        np.repeat(history[None, :], len(bp), axis=0),
    ])
    pred_l = np.column_stack([
        m.predict(features) for m in selector["selectors"]
    ])
    pred_l = np.where(np.isfinite(pred_l), pred_l, np.log(2.0))
    pred_voi = None
    if selector.get("voi_selectors"):
        pred_voi = np.column_stack([
            m.predict(features) for m in selector["voi_selectors"]
        ])
        pred_voi = np.where(np.isfinite(pred_voi), pred_voi, 0.0)
    return route_uncertainty_score(
        pred_l, bp, ctx, baseline=_clip_prob(baseline),
        predicted_voi=pred_voi,
    )


def apply_recalibration(p, calibration):
    """Apply an accepted temporal calibrator; otherwise return raw probabilities."""
    p = _clip_prob(p)
    if not isinstance(calibration, dict) or not calibration.get("accepted"):
        return p
    method = str(calibration.get("method") or "none")
    model = calibration.get("model")
    if model is None or method == "none":
        return p
    if method == "sigmoid":
        z = np.log(p / (1.0 - p)).reshape(-1, 1)
        return _clip_prob(model.predict_proba(z)[:, 1])
    if method == "beta":
        z = np.column_stack([np.log(p), np.log(1.0 - p)])
        return _clip_prob(model.predict_proba(z)[:, 1])
    if method == "isotonic":
        return _clip_prob(model.predict(p))
    raise ValueError(f"unsupported calibration method: {method}")


def bootstrap_fold_improvement(fold_deltas, seed=20260924, draws=1000):
    """Fold-level bootstrap: positive values mean lower candidate log loss."""
    d = np.asarray(fold_deltas, dtype=float)
    if len(d) < 6 or not np.isfinite(d).all():
        return {
            "probability_improvement": 0.0,
            "p05_improvement": float("-inf"),
        }
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(draws, len(d)))
    boot_delta = d[idx].mean(axis=1)
    improvement = -boot_delta
    return {
        "probability_improvement": float(np.mean(improvement > 0.0)),
        "p05_improvement": float(np.quantile(improvement, 0.05)),
    }


def bootstrap_clustered_improvement(fold_deltas, fold_groups, seed=20260924, draws=2000):
    """Cluster-bootstrap row-level calibration deltas by physical event."""
    if not fold_deltas or not fold_groups or len(fold_deltas) != len(fold_groups):
        return {
            "probability_improvement": 0.0,
            "p05_improvement": float("-inf"),
            "clusters": 0,
        }
    rng = np.random.default_rng(seed)
    fold_means = []
    cluster_count = 0
    for delta, groups in zip(fold_deltas, fold_groups):
        d = np.asarray(delta, dtype=float)
        g = np.asarray(groups, dtype=object)
        if len(d) == 0 or len(d) != len(g) or not np.isfinite(d).all():
            continue
        unique = np.unique(g)
        if len(unique) < 5:
            return {
                "probability_improvement": 0.0,
                "p05_improvement": float("-inf"),
                "clusters": int(len(unique)),
            }
        cluster_values = np.asarray([
            float(np.mean(d[g == key])) for key in unique
        ], dtype=float)
        cluster_count += len(cluster_values)
        idx = rng.integers(0, len(cluster_values), size=(draws, len(cluster_values)))
        boot_fold = cluster_values[idx].mean(axis=1)
        fold_means.append(boot_fold)
    if not fold_means:
        return {
            "probability_improvement": 0.0,
            "p05_improvement": float("-inf"),
            "clusters": int(cluster_count),
        }
    improvement = -np.mean(np.column_stack(fold_means), axis=1)
    return {
        "probability_improvement": float(np.mean(improvement > 0.0)),
        "p05_improvement": float(np.quantile(improvement, 0.05)),
        "clusters": int(cluster_count),
    }


def temporal_recalibration(p, y, groups=None):
    """
    Fit a low-capacity calibrator only on pre-holdout sequential data.

    Method choice is made on expanding temporal validation blocks. A
    recalibrator is accepted only when it improves log loss by a minimum
    amount, does not materially worsen Brier score, and shows stable positive
    improvement under a fold-level bootstrap.
    """
    p = _clip_prob(p)
    y = np.asarray(y, dtype=int)
    if groups is None:
        groups = np.arange(len(p), dtype=object)
    else:
        groups = np.asarray(groups, dtype=object)
        if len(groups) != len(p):
            return {
                "accepted": False,
                "method": "none",
                "reason": "calibration_group_shape_mismatch",
            }
    n = len(p)
    if n < 300 or len(np.unique(y)) < 2:
        return {
            "accepted": False,
            "method": "none",
            "reason": "insufficient_preholdout_oof",
        }

    cuts = sorted(set([
        max(120, int(n * 0.40)),
        max(150, int(n * 0.50)),
        max(180, int(n * 0.60)),
        max(210, int(n * 0.70)),
        max(240, int(n * 0.80)),
        max(270, int(n * 0.90)),
    ]))
    cuts = [c for c in cuts if c < n - 30]
    folds = []
    for i, te_start in enumerate(cuts):
        te_end = cuts[i + 1] if i + 1 < len(cuts) else n
        if te_end - te_start < 30:
            continue
        if len(np.unique(y[:te_start])) < 2 or len(np.unique(y[te_start:te_end])) < 2:
            continue
        folds.append((te_start, te_end))
    if len(folds) < 5:
        return {
            "accepted": False,
            "method": "none",
            "reason": "insufficient_temporal_calibration_folds",
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
            m.fit(np.column_stack([np.log(train_p), np.log(1.0 - train_p)]), train_y)
            at = np.column_stack([np.log(test_p), np.log(1.0 - test_p)])
            return _clip_prob(m.predict_proba(at)[:, 1]), m
        if method == "isotonic":
            if len(train_p) < 120 or len(np.unique(train_p)) < 25:
                return None, None
            m = IsotonicRegression(y_min=EPS, y_max=1.0-EPS, out_of_bounds="clip")
            m.fit(train_p, train_y)
            return _clip_prob(m.predict(test_p)), m
        raise ValueError(method)

    from src.research_cycle_v4 import metric
    methods = ["none", "sigmoid", "beta", "isotonic"]
    scores = {m: [] for m in methods}
    predictions = {m: {} for m in methods}
    fold_scores = {m: {} for m in methods}
    bounds = list(folds)

    for fold_index, (a, b) in enumerate(bounds):
        for method in methods:
            pp, _ = fit_predict(method, p[:a], y[:a], p[a:b])
            if pp is None:
                continue
            score = metric(y[a:b], pp)
            scores[method].append(score)
            fold_scores[method][fold_index] = score
            predictions[method][fold_index] = np.asarray(pp, dtype=float)

    raw = scores["none"]
    if len(raw) < 5:
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
        if m == "none" or len(v) >= 5
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

    bootstrap = {"probability_improvement": 0.0, "p05_improvement": float("-inf")}
    cluster_bootstrap = {"probability_improvement": 0.0, "p05_improvement": float("-inf"), "clusters": 0}
    if method != "none":
        common_folds = sorted(set(fold_scores["none"]).intersection(fold_scores[method]))
        fold_deltas = [
            float(fold_scores[method][i]["logloss"] - fold_scores["none"][i]["logloss"])
            for i in common_folds
        ]
        bootstrap = bootstrap_fold_improvement(
            fold_deltas, seed=20260924, draws=2000
        )
        candidate_preds = predictions.get(method, {})
        raw_preds = predictions.get("none", {})
        cluster_deltas = []
        cluster_groups = []
        for i in sorted(set(candidate_preds).intersection(raw_preds)):
            a, b = bounds[i]
            cp = np.asarray(candidate_preds[i], dtype=float)
            rp = np.asarray(raw_preds[i], dtype=float)
            if len(cp) != (b - a) or len(rp) != (b - a):
                continue
            delta = _bce_loss(cp, y[a:b]) - _bce_loss(rp, y[a:b])
            cluster_deltas.append(delta)
            cluster_groups.append(groups[a:b])
        cluster_bootstrap = bootstrap_clustered_improvement(
            cluster_deltas, cluster_groups, seed=20260924, draws=2000
        )

    accepted = (
        method != "none"
        and cand_obj <= raw_obj - max(0.001, 0.003 * raw_obj)
        and cand_brier <= raw_brier + 0.002
        and bootstrap["probability_improvement"] >= 0.90
        and bootstrap["p05_improvement"] > 0.0
        and cluster_bootstrap["probability_improvement"] >= 0.90
        and cluster_bootstrap["p05_improvement"] > 0.0
    )
    if not accepted:
        return {
            "accepted": False,
            "method": "none",
            "reason": "recalibration_did_not_pass_temporal_bootstrap_gate",
            "selected_candidate": method,
            "candidate_methods": candidates,
            "bootstrap": bootstrap,
            "cluster_bootstrap": cluster_bootstrap,
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
        "bootstrap": bootstrap,
        "cluster_bootstrap": cluster_bootstrap,
    }


__all__ = [
    "predictive_entropy",
    "uncertainty_features",
    "population_drift_features",
    "route_uncertainty_score",
    "expert_voi_targets",
    "fit_uncertainty_loss_selector",
    "evaluate_oof",
    "temporal_recalibration",
    "fit_final_selector_from_folds",
    "route_with_selector",
    "apply_recalibration",
    "bootstrap_fold_improvement",
    "bootstrap_clustered_improvement",
]
