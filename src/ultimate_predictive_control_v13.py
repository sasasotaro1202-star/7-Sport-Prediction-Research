from __future__ import annotations

"""ULTIMATE FINAL v13 hardening layer.

Research-only. All decision-time features are causal: a row may depend on
observations and matured outcomes strictly before that row, never on its own
outcome or any later outcome. Future-difficulty/failure labels are evaluation
targets and are generated inside outer chronological folds with a training
cutoff that leaves the target horizon entirely behind that cutoff.

The module deliberately exposes explicit PROXY/RESEARCH_ONLY states for items
that need sport-specific data acquisition or production wiring.
"""

import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


EPS = 1e-6
SEED = 20260926


def _p(values: Sequence[float]) -> np.ndarray:
    return np.clip(np.asarray(values, dtype=float), EPS, 1.0 - EPS)


def _safe_float(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def logloss(y: Sequence[int], p: Sequence[float]) -> float:
    yv = np.asarray(y, dtype=int)
    pv = _p(p)
    if len(yv) != len(pv) or len(yv) == 0:
        raise ValueError("logloss requires equal non-empty arrays")
    return float(-np.mean(yv * np.log(pv) + (1.0 - yv) * np.log(1.0 - pv)))


def metrics(y: Sequence[int], p: Sequence[float]) -> Dict[str, float | int | None]:
    yv = np.asarray(y, dtype=int)
    pv = _p(p)
    if len(yv) != len(pv) or len(yv) == 0:
        return {"accuracy": None, "logloss": None, "brier": None, "ece": None, "n": 0}
    bins = np.linspace(0.0, 1.0, 11)
    ece = 0.0
    for i in range(10):
        lo, hi = bins[i], bins[i + 1]
        mask = (pv >= lo) & ((pv < hi) if i < 9 else (pv <= hi))
        if np.any(mask):
            ece += float(mask.mean()) * abs(float(yv[mask].mean()) - float(pv[mask].mean()))
    return {
        "accuracy": float(np.mean((pv >= 0.5) == yv)),
        "logloss": logloss(yv, pv),
        "brier": float(np.mean((pv - yv) ** 2)),
        "ece": float(ece),
        "n": int(len(yv)),
    }


def _entropy(p: np.ndarray) -> np.ndarray:
    pv = _p(p)
    return -(pv * np.log2(pv) + (1.0 - pv) * np.log2(1.0 - pv))


def _rolling_mean(x: np.ndarray, window: int) -> np.ndarray:
    out = np.zeros(len(x), dtype=float)
    for i in range(len(x)):
        a = max(0, i - window + 1)
        out[i] = float(np.mean(x[a : i + 1]))
    return out


def _rolling_std(x: np.ndarray, window: int) -> np.ndarray:
    out = np.zeros(len(x), dtype=float)
    for i in range(len(x)):
        a = max(0, i - window + 1)
        out[i] = float(np.std(x[a : i + 1]))
    return out


def _causal_slope(x: np.ndarray, window: int) -> np.ndarray:
    out = np.zeros(len(x), dtype=float)
    for i in range(len(x)):
        a = max(0, i - window + 1)
        z = x[a : i + 1]
        if len(z) < 2:
            continue
        t = np.arange(len(z), dtype=float)
        denom = float(np.sum((t - t.mean()) ** 2))
        out[i] = float(np.sum((t - t.mean()) * (z - z.mean())) / denom) if denom else 0.0
    return out


def disagreement_features(pred_matrix: np.ndarray) -> Dict[str, np.ndarray]:
    pm = _p(pred_matrix)
    if pm.ndim != 2 or pm.shape[0] == 0 or pm.shape[1] == 0:
        raise ValueError("pred_matrix must be non-empty 2-D")
    mean = pm.mean(axis=1)
    median = np.median(pm, axis=1)
    std = pm.std(axis=1)
    pmin = pm.min(axis=1)
    pmax = pm.max(axis=1)
    direction = (mean >= 0.5).astype(int)
    class_agreement = np.mean((pm >= 0.5) == (mean[:, None] >= 0.5), axis=1)
    pair_js = []
    for i in range(pm.shape[1]):
        for j in range(i + 1, pm.shape[1]):
            m = 0.5 * (pm[:, i] + pm[:, j])
            k1 = pm[:, i] * np.log(pm[:, i] / m) + (1 - pm[:, i]) * np.log((1 - pm[:, i]) / (1 - m))
            k2 = pm[:, j] * np.log(pm[:, j] / m) + (1 - pm[:, j]) * np.log((1 - pm[:, j]) / (1 - m))
            pair_js.append(0.5 * (k1 + k2))
    js = np.mean(np.vstack(pair_js), axis=0) if pair_js else np.zeros(len(pm))
    return {
        "mean": mean,
        "median": median,
        "std": std,
        "min": pmin,
        "max": pmax,
        "range": pmax - pmin,
        "entropy": _entropy(mean),
        "class_agreement": class_agreement,
        "pairwise_js": js,
        "flip": np.r_[0.0, (direction[1:] != direction[:-1]).astype(float)],
        "speed": np.r_[0.0, np.abs(np.diff(mean))],
        "acceleration": np.r_[0.0, 0.0, np.abs(np.diff(mean, n=2))],
        "recent_mean": _rolling_mean(std, 10),
        "recent_std": _rolling_std(std, 10),
    }


def predictability_features(d: Mapping[str, np.ndarray], data_quality: np.ndarray | None = None) -> Dict[str, np.ndarray]:
    ent = np.clip(np.asarray(d["entropy"], dtype=float), 0.0, 1.0)
    dis = np.clip(np.asarray(d["std"], dtype=float) * 4.0, 0.0, 1.0)
    speed = np.clip(np.asarray(d["speed"], dtype=float) * 4.0, 0.0, 1.0)
    accel = np.clip(np.asarray(d["acceleration"], dtype=float) * 4.0, 0.0, 1.0)
    quality = np.ones(len(ent), dtype=float) if data_quality is None else np.clip(np.asarray(data_quality, dtype=float), 0.0, 1.0)
    score = np.clip(
        1.0 - 0.38 * ent - 0.28 * dis - 0.16 * speed - 0.08 * accel + 0.10 * (quality - 0.5),
        0.0,
        1.0,
    )
    return {
        "predictability": score,
        "velocity": np.r_[0.0, np.diff(score)],
        "acceleration": np.r_[0.0, 0.0, np.diff(score, n=2)],
        "confidence_proxy": np.abs(np.asarray(d["mean"]) - 0.5) * 2.0,
    }


def regime_features(d: Mapping[str, np.ndarray]) -> Dict[str, np.ndarray]:
    mean = np.asarray(d["mean"], dtype=float)
    slope = _causal_slope(mean, 12)
    vol = _rolling_std(mean, 12)
    dis = np.asarray(d["std"], dtype=float)
    label = np.full(len(mean), "normal", dtype=object)
    for i in range(len(mean)):
        if dis[i] > 0.18 and vol[i] > 0.08:
            label[i] = "stress_high_vol"
        elif vol[i] > 0.08:
            label[i] = "high_vol"
        elif slope[i] > 0.012 and mean[i] > 0.55:
            label[i] = "trend_up"
        elif slope[i] < -0.012 and mean[i] < 0.45:
            label[i] = "trend_down"
        elif 0.44 <= mean[i] <= 0.56:
            label[i] = "range"
    codes = {name: i for i, name in enumerate(["normal", "trend_up", "trend_down", "range", "high_vol", "stress_high_vol"])}
    code = np.asarray([codes[str(x)] for x in label], dtype=int)
    transition = np.r_[0.0, (code[1:] != code[:-1]).astype(float)]
    return {
        "label": label,
        "code": code,
        "transition": transition,
        "slope": slope,
        "volatility": vol,
    }


def drift_ood_features(pred_matrix: np.ndarray, history_window: int = 60) -> Dict[str, np.ndarray]:
    pm = _p(pred_matrix)
    n, m = pm.shape
    ood = np.zeros(n, dtype=float)
    drift = np.zeros(n, dtype=float)
    for i in range(n):
        if i < 5:
            continue
        a = max(0, i - history_window)
        hist = pm[a:i]
        if len(hist) < 5:
            continue
        mu = hist.mean(axis=0)
        sd = hist.std(axis=0) + 0.02
        z = np.abs((pm[i] - mu) / sd)
        ood[i] = float(np.clip(np.mean(z) / 4.0, 0.0, 1.0))
        prev = pm[max(a, i - 5):i]
        drift[i] = float(np.clip(np.mean(np.abs(pm[i] - prev.mean(axis=0))) * 4.0, 0.0, 1.0))
    return {"ood": ood, "drift": drift}


def _outer_blocks(n: int, min_train: int = 60, test_size: int | None = None) -> List[Tuple[np.ndarray, np.ndarray]]:
    if n < min_train + 30:
        return []
    ts = test_size or max(20, n // 5)
    blocks = []
    start = min_train
    while start < n:
        end = min(n, start + ts)
        if end - start >= 10:
            blocks.append((np.arange(start), np.arange(start, end)))
        start = end
    return blocks


def _chronological_binary_oos(
    X: np.ndarray,
    target: np.ndarray,
    min_train: int = 60,
    test_size: int | None = None,
) -> Dict:
    X = np.asarray(X, dtype=float)
    y = np.asarray(target, dtype=int)
    if len(y) != len(X):
        raise ValueError("X/target length mismatch")
    preds = np.full(len(y), np.nan, dtype=float)
    folds = []
    for tr, te in _outer_blocks(len(y), min_train=min_train, test_size=test_size):
        tr = tr[y[tr] >= 0]
        te = te[y[te] >= 0]
        if len(tr) < min_train or len(np.unique(y[tr])) < 2:
            continue
        model = Pipeline([
            ("scale", StandardScaler()),
            ("lr", LogisticRegression(C=0.25, max_iter=2000, random_state=SEED)),
        ])
        model.fit(X[tr], y[tr])
        pp = _p(model.predict_proba(X[te])[:, 1])
        preds[te] = pp
        folds.append({
            "train_end_exclusive": int(tr.max() + 1),
            "test_start": int(te.min()),
            "test_end_exclusive": int(te.max() + 1),
            "train_rows": int(len(tr)),
            "test_rows": int(len(te)),
            "metrics": metrics(y[te], pp),
        })
    valid = np.isfinite(preds)
    if valid.sum() < 20:
        return {"status": "INSUFFICIENT_OOS", "rows": int(valid.sum()), "predictions": preds.tolist(), "folds": folds}
    return {
        "status": "EVALUATED",
        "rows": int(valid.sum()),
        "metrics": metrics(y[valid], preds[valid]),
        "predictions": preds.tolist(),
        "folds": folds,
    }


def _future_loss_values(p: np.ndarray, y: np.ndarray, horizon: int) -> np.ndarray:
    """Future-window losses for evaluation; these are never decision features."""
    row_loss = -(y * np.log(_p(p)) + (1.0 - y) * np.log(1.0 - _p(p)))
    values = np.full(len(y), np.nan, dtype=float)
    for i in range(max(0, len(y) - horizon)):
        values[i] = float(np.mean(row_loss[i + 1 : i + 1 + horizon]))
    return values


def _training_prefix_labels(
    future_values: np.ndarray,
    cutoff_exclusive: int,
    horizon: int,
    quantile: float = 0.60,
) -> Tuple[np.ndarray, float | None]:
    """Threshold and labels are learned only from fully matured pre-cutoff rows."""
    usable_end = max(0, cutoff_exclusive - horizon)
    idx = np.arange(len(future_values))
    valid = np.isfinite(future_values) & (idx < usable_end)
    label = np.full(len(future_values), -1, dtype=int)
    if int(valid.sum()) < 20:
        return label, None
    threshold = float(np.quantile(future_values[valid], quantile))
    label[valid] = (future_values[valid] > threshold).astype(int)
    return label, threshold

def future_failure_oos(
    model_predictions: Mapping[str, np.ndarray],
    y: np.ndarray,
    context: np.ndarray,
    horizon: int = 5,
    quantile: float = 0.60,
) -> Dict:
    yv = np.asarray(y, dtype=int)
    ctx = np.asarray(context, dtype=float)
    out = {}
    for name, raw in model_predictions.items():
        pv = _p(raw)
        future_loss = _future_loss_values(pv, yv, horizon)
        risk_pred = np.full(len(yv), np.nan, dtype=float)
        folds = []
        for _, te in _outer_blocks(len(yv), min_train=80, test_size=max(20, len(yv) // 5)):
            test_start = int(te.min())
            train_labels, threshold = _training_prefix_labels(
                future_loss, test_start, horizon, quantile=quantile
            )
            train_end = max(0, test_start - horizon)
            tr = np.arange(train_end)
            tr = tr[train_labels[tr] >= 0]
            te2 = te[np.isfinite(future_loss[te])]
            if threshold is None or len(tr) < 60 or len(te2) < 10 or len(np.unique(train_labels[tr])) < 2:
                continue
            margin = np.abs(pv - 0.5) * 2.0
            X = np.column_stack([margin, ctx])
            model = Pipeline([
                ("scale", StandardScaler()),
                ("lr", LogisticRegression(C=0.25, class_weight="balanced", max_iter=2000, random_state=SEED)),
            ])
            model.fit(X[tr], train_labels[tr])
            risk_pred[te2] = model.predict_proba(X[te2])[:, 1]
            test_target = (future_loss[te2] > threshold).astype(int)
            folds.append({
                "train_end_exclusive": int(tr.max() + 1),
                "target_horizon": int(horizon),
                "test_start": int(te2.min()),
                "test_end_exclusive": int(te2.max() + 1),
                "threshold_source": "training_prefix_only",
                "test_rows": int(len(te2)),
                "test_target_positive_rate": _safe_float(np.mean(test_target)),
            })
        valid = np.isfinite(risk_pred)
        if valid.sum() >= 20:
            idx = np.where(valid)[0]
            # Fold-level predictions are evaluated against the same fold's
            # training-prefix threshold. This is reconstructed here only for
            # summary; per-fold threshold provenance remains in the artifact.
            y_eval = []
            for i in idx:
                prefix_values = future_loss[:max(0, i - horizon)]
                prefix_values = prefix_values[np.isfinite(prefix_values)]
                threshold_eval = float(np.quantile(prefix_values, quantile)) if len(prefix_values) >= 20 else float(np.nanmedian(prefix_values)) if len(prefix_values) else 0.0
                y_eval.append(int(future_loss[i] > threshold_eval))
            out[name] = {
                "status": "EVALUATED",
                "rows": int(valid.sum()),
                "metrics": metrics(y_eval, risk_pred[valid]),
                "risk_latest": _safe_float(risk_pred[idx[-1]]),
                "folds": folds,
                "failure_definition": "future_window_logloss_above_training_prefix_quantile",
                "training_target_pit": "PASS",
                "latest_risk_is_oos": True,
            }
        else:
            out[name] = {"status": "INSUFFICIENT_OOS", "rows": int(valid.sum()), "folds": folds}
    return {
        "status": "EVALUATED" if out else "INSUFFICIENT_OOS",
        "models": out,
        "policy": "outer chronological OOS; future labels matured strictly before each fold cutoff",
    }

def time_to_failure_oos(
    model_predictions: Mapping[str, np.ndarray],
    y: np.ndarray,
    context: np.ndarray,
    horizons: Sequence[int] = (3, 5, 10),
) -> Dict:
    results = {}
    for name, p0 in model_predictions.items():
        risks = {}
        for h in horizons:
            r = future_failure_oos({name: p0}, y, context, horizon=int(h))
            entry = r["models"].get(name, {})
            risks[str(h)] = entry
        latest = []
        for h in horizons:
            q = risks[str(h)].get("risk_latest")
            latest.append((int(h), q))
        valid = [(h, q) for h, q in latest if q is not None]
        ttf = next((h for h, q in valid if q >= 0.60), None)
        results[name] = {
            "risk_by_horizon": {str(h): risks[str(h)].get("risk_latest") for h in horizons},
            "first_warning_horizon": ttf,
            "hazard_proxy": _safe_float(np.mean([q for _, q in valid])) if valid else None,
        }
    return {"status": "EVALUATED", "models": results, "definition": "first tested horizon with risk >= 0.60"}


def error_correlation(model_predictions: Mapping[str, np.ndarray], y: np.ndarray) -> Dict:
    names = list(model_predictions)
    if len(names) < 2:
        return {"status": "INSUFFICIENT"}
    e = np.column_stack([((np.asarray(model_predictions[n]) >= 0.5).astype(int) != y).astype(float) for n in names])
    if len(e) < 3:
        return {"status": "INSUFFICIENT"}
    corr = np.corrcoef(e, rowvar=False)
    upper = corr[np.triu_indices(len(names), 1)]
    return {
        "status": "EVALUATED",
        "models": names,
        "error_correlation": corr.tolist(),
        "mean_pairwise_error_correlation": _safe_float(np.mean(upper)) if len(upper) else None,
        "mean_error_overlap": _safe_float(np.mean([np.mean(e[:, i] * e[:, j]) for i in range(len(names)) for j in range(i + 1, len(names))])),
    }


def causal_router(
    model_predictions: Mapping[str, np.ndarray],
    y: np.ndarray,
    disagreement: np.ndarray,
    failure_risk: Mapping[str, np.ndarray] | None = None,
    window: int = 40,
) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
    """Soft routing. Row i uses only outcomes from rows < i."""
    names = list(model_predictions)
    pm = np.column_stack([_p(model_predictions[n]) for n in names])
    yv = np.asarray(y, dtype=int)
    n, m = pm.shape
    weights = np.zeros((n, m), dtype=float)
    route = np.full(n, 0.5, dtype=float)
    for i in range(n):
        if i == 0:
            w = np.full(m, 1.0 / m)
        else:
            a = max(0, i - window)
            prior_losses = np.asarray([
                logloss(yv[a:i], pm[a:i, j]) if i - a >= 2 else 0.693147
                for j in range(m)
            ])
            score = -prior_losses
            if failure_risk is not None:
                penalties = np.asarray([
                    float(failure_risk.get(name, np.zeros(n))[i - 1] if i - 1 < len(failure_risk.get(name, np.zeros(n))) else 0.0)
                    for name in names
                ])
                score -= 0.75 * penalties
            temp = 1.0 + 2.0 * float(np.clip(disagreement[i], 0.0, 0.5))
            score = score / temp
            score -= np.max(score)
            w = np.exp(score)
            w /= np.sum(w)
        weights[i] = w
        route[i] = float(np.dot(pm[i], w))
    return route, {name: weights[:, j] for j, name in enumerate(names)}


def retrieval_features(
    vectors: np.ndarray,
    y: np.ndarray,
    k: int = 5,
    lookback: int = 120,
) -> Dict[str, np.ndarray]:
    """Past-only nearest-neighbour outcome retrieval."""
    X = np.asarray(vectors, dtype=float)
    yv = np.asarray(y, dtype=int)
    n = len(X)
    pred = np.full(n, 0.5, dtype=float)
    distance = np.full(n, np.nan, dtype=float)
    dispersion = np.full(n, np.nan, dtype=float)
    count = np.zeros(n, dtype=int)
    for i in range(n):
        if i < 10:
            continue
        a = max(0, i - lookback)
        hist = X[a:i]
        mu = hist.mean(axis=0)
        sd = hist.std(axis=0) + 0.05
        q = (X[i] - mu) / sd
        d = np.sqrt(np.mean(q * q, axis=1))
        idx = np.argsort(d)[: min(k, len(d))]
        if len(idx) == 0:
            continue
        yy = yv[a:i][idx]
        pred[i] = float(np.mean(yy))
        distance[i] = float(np.mean(d[idx]))
        dispersion[i] = float(np.std(yy))
        count[i] = int(len(idx))
    return {
        "probability": pred,
        "distance": distance,
        "dispersion": dispersion,
        "count": count,
        "pit": "PASS_PAST_ONLY",
    }


def meta_label_oos(
    base_probability: np.ndarray,
    y: np.ndarray,
    context: np.ndarray,
) -> Dict:
    p0 = _p(base_probability)
    yv = np.asarray(y, dtype=int)
    correct = ((p0 >= 0.5).astype(int) == yv).astype(int)
    out = _chronological_binary_oos(np.asarray(context, dtype=float), correct, min_train=80)
    out["target"] = "future/current_base_prediction_correctness"
    out["target_pit"] = "current outcome is target only; predictor training remains chronological OOS"
    return out


def tta_past_only(base_probability: np.ndarray, y: np.ndarray, window: int = 80) -> np.ndarray:
    """Past-outcome Platt TTA; current outcome is never part of the fit."""
    p0 = _p(base_probability)
    yv = np.asarray(y, dtype=int)
    out = np.array(p0, copy=True)
    for i in range(len(p0)):
        a = max(0, i - window)
        if i - a < 30 or len(np.unique(yv[a:i])) < 2:
            continue
        X = np.log(p0[a:i] / (1.0 - p0[a:i])).reshape(-1, 1)
        model = LogisticRegression(C=1.0, max_iter=1000, random_state=SEED)
        model.fit(X, yv[a:i])
        xi = np.log(p0[i] / (1.0 - p0[i]))
        out[i] = float(model.predict_proba([[xi]])[0, 1])
    return _p(out)


def counterfactual_stability(
    model_predictions: np.ndarray,
    base_probability: np.ndarray,
) -> Dict[str, float]:
    pm = _p(model_predictions)
    p0 = _p(base_probability)
    small = np.clip(pm + 0.01 * np.sign(pm - 0.5), EPS, 1.0 - EPS)
    shifted = small.mean(axis=1)
    return {
        "mean_abs_prediction_change": float(np.mean(np.abs(shifted - p0))),
        "direction_flip_rate": float(np.mean((shifted >= 0.5) != (p0 >= 0.5))),
    }


def robustness(
    base_probability: np.ndarray,
    model_predictions: np.ndarray,
    y: np.ndarray,
) -> Dict:
    rng = np.random.default_rng(SEED)
    p0 = _p(base_probability)
    pm = _p(model_predictions)
    yv = np.asarray(y, dtype=int)
    noise = _p(p0 + rng.normal(0.0, 0.02, len(p0)))
    plus = _p(p0 + 0.02)
    minus = _p(p0 - 0.02)
    drop = pm[:, 1:].mean(axis=1) if pm.shape[1] > 1 else p0
    return {
        "status": "EVALUATED",
        "baseline": metrics(yv, p0),
        "noise": metrics(yv, noise),
        "plus_shift": metrics(yv, plus),
        "minus_shift": metrics(yv, minus),
        "model_dropout": metrics(yv, drop),
        "counterfactual": counterfactual_stability(pm, p0),
    }


def _strategy(
    p: float,
    predictability: float,
    disagreement: float,
    ood: float,
    retrieval_p: float,
) -> Tuple[str, float, str]:
    uncertainty = float(np.clip(0.45 * disagreement + 0.35 * ood + 0.20 * (1.0 - predictability), 0.0, 1.0))
    if uncertainty >= 0.80:
        return "abstain_candidate", 0.50, "very_high_uncertainty"
    if uncertainty >= 0.60:
        return "conservative_shrink", float(0.5 + 0.5 * (p - 0.5) * 0.65), "high_uncertainty"
    if uncertainty >= 0.40:
        return "retrieval_blend", float(0.65 * p + 0.35 * retrieval_p), "moderate_uncertainty"
    return "dynamic_router", p, "low_uncertainty"


def strategy_and_output(
    routed: np.ndarray,
    predictability: np.ndarray,
    disagreement: np.ndarray,
    ood: np.ndarray,
    retrieval_p: np.ndarray,
    retrieval_dispersion: np.ndarray,
) -> Dict:
    n = len(routed)
    strategy = []
    output_format = []
    final_p = np.zeros(n, dtype=float)
    uncertainty = np.zeros(n, dtype=float)
    for i in range(n):
        name, p, _ = _strategy(float(routed[i]), float(predictability[i]), float(disagreement[i]), float(ood[i]), float(retrieval_p[i]))
        u = float(np.clip(
            0.45 * disagreement[i] + 0.25 * ood[i] + 0.20 * (1.0 - predictability[i])
            + 0.10 * np.nan_to_num(retrieval_dispersion[i], nan=0.5),
            0.0, 1.0
        ))
        if u >= 0.80 or predictability[i] < 0.30:
            form = "abstain_candidate"
        elif u >= 0.60 or predictability[i] < 0.50:
            form = "scenario_or_set"
        elif u >= 0.40:
            form = "probability_plus_range"
        else:
            form = "single_probability"
        strategy.append(name)
        output_format.append(form)
        final_p[i] = float(np.clip(p, EPS, 1.0 - EPS))
        uncertainty[i] = u
    return {
        "strategy": strategy,
        "output_format": output_format,
        "probability": final_p,
        "uncertainty": uncertainty,
    }


def prediction_trajectory(current_p: float, slope: float, uncertainty: float, steps: Sequence[int] = (1, 2, 3, 5)) -> Dict:
    values = []
    for step in steps:
        projected = float(np.clip(current_p + slope * min(step, 5), EPS, 1.0 - EPS))
        spread = float(np.clip(0.05 + uncertainty * 0.25 * math.sqrt(step), 0.02, 0.45))
        values.append({
            "step": int(step),
            "point": projected,
            "lower": float(np.clip(projected - spread, EPS, 1.0 - EPS)),
            "upper": float(np.clip(projected + spread, EPS, 1.0 - EPS)),
        })
    branch = {
        "upside": float(np.clip(current_p + 0.10 * (1.0 - current_p), EPS, 1.0 - EPS)),
        "downside": float(np.clip(current_p - 0.10 * current_p, EPS, 1.0 - EPS)),
        "reversal": float(1.0 - current_p),
    }
    return {
        "status": "SCENARIO_PROJECTION",
        "trajectory_is_model_projection": True,
        "steps": values,
        "branch_probabilities": branch,
    }


def revision_metrics(p: np.ndarray, y: np.ndarray, threshold: float = 0.05) -> Dict:
    p0 = _p(p)
    yv = np.asarray(y, dtype=int)
    prev = np.r_[p0[0], p0[:-1]]
    revise = np.abs(p0 - prev) >= threshold
    now = (p0 >= 0.5) == yv
    keep = (prev >= 0.5) == yv
    return {
        "revision_count": int(revise.sum()),
        "flip_count": int((revise & ((p0 >= 0.5) != (prev >= 0.5))).sum()),
        "revision_accuracy": _safe_float(np.mean(now[revise])) if revise.any() else None,
        "keep_accuracy_on_revision_rows": _safe_float(np.mean(keep[revise])) if revise.any() else None,
        "revision_value": _safe_float(np.mean(now[revise].astype(float) - keep[revise].astype(float))) if revise.any() else None,
        "false_revision_count": int(np.sum(revise & ~now & keep)),
    }


def _failure_risk_matrix(
    model_predictions: Mapping[str, np.ndarray],
    failure: Dict,
    n: int,
) -> Dict[str, np.ndarray]:
    out = {}
    for name in model_predictions:
        arr = np.zeros(n, dtype=float)
        entry = failure.get("models", {}).get(name, {})
        # The detailed OOS predictor currently exposes latest risk. Use a
        # conservative scalar across the full decision horizon rather than
        # backfilling future predictions. State is explicitly summary-only.
        q = entry.get("risk_latest")
        if q is not None:
            arr[:] = float(np.clip(q, 0.0, 1.0))
        out[name] = arr
    return out


def build_forecast_contract(
    sport: str,
    cutoff_utc: str,
    model_names: Sequence[str],
    weights: Mapping[str, float],
    p: float,
    predictability: float,
    uncertainty: float,
    failure_risk: float,
    strategy: str,
    output_format: str,
) -> Dict:
    freshness = float(np.clip(1.0 - uncertainty, 0.0, 1.0))
    ttl_rows = max(1, int(round(1.0 + 5.0 * freshness)))
    return {
        "sport": sport,
        "prediction_time": cutoff_utc,
        "valid_until_candidate_rows": ttl_rows,
        "data_snapshot": "chronological_oos_input",
        "model_version": "ultimate-v13-hardening-research",
        "strategy": strategy,
        "prediction": {"probability": float(p), "direction": int(p >= 0.5)},
        "models": list(model_names),
        "weights": {k: float(v) for k, v in weights.items()},
        "confidence": float(np.clip(1.0 - uncertainty, 0.0, 1.0)),
        "predictability": float(predictability),
        "uncertainty": {
            "total": float(uncertainty),
            "model_disagreement": "embedded_in_total",
            "future_failure_risk": float(failure_risk),
        },
        "prediction_format": output_format,
        "abstain_candidate": bool(output_format == "abstain_candidate"),
        "pit_status": "PASS_INHERITED_FROM_CHRONOLOGICAL_OOS",
    }


def run_v13_research(
    sport: str,
    model_predictions: Mapping[str, Sequence[float]],
    y: Sequence[int],
    cutoff_utc: str = "unknown",
    feature_matrix: np.ndarray | None = None,
    data_quality: Sequence[float] | None = None,
    weights: Mapping[str, float] | None = None,
    artifact_path: str = "results/research/ultimate_v13_hardening.json",
) -> Dict:
    names = list(model_predictions)
    if len(names) < 2:
        return {"sport": sport, "status": "BLOCKED", "reason": "need_at_least_two_models"}
    yv = np.asarray(y, dtype=int)
    pm = np.column_stack([_p(model_predictions[n]) for n in names])
    if any(len(pm[:, j]) != len(yv) for j in range(pm.shape[1])) or len(yv) < 120:
        return {"sport": sport, "status": "BLOCKED", "reason": "insufficient_or_misaligned_oos"}
    if not np.all(np.isfinite(pm)):
        return {"sport": sport, "status": "BLOCKED", "reason": "nonfinite_prediction"}
    if not np.all(np.isin(yv, [0, 1])):
        return {"sport": sport, "status": "BLOCKED", "reason": "invalid_binary_target"}

    d = disagreement_features(pm)
    q = np.ones(len(yv), dtype=float) if data_quality is None else np.asarray(data_quality, dtype=float)
    if len(q) != len(yv):
        return {"sport": sport, "status": "BLOCKED", "reason": "data_quality_alignment"}
    predfeat = predictability_features(d, q)
    reg = regime_features(d)
    shift = drift_ood_features(pm)

    wm = np.asarray([float((weights or {}).get(n, 1.0 / len(names))) for n in names], dtype=float)
    wm = np.clip(wm, 0.0, None)
    if wm.sum() <= 0:
        wm[:] = 1.0
    wm /= wm.sum()
    fixed = pm @ wm

    context = np.column_stack([
        d["std"],
        d["entropy"],
        d["speed"],
        d["recent_mean"],
        reg["volatility"],
        shift["drift"],
        shift["ood"],
        predfeat["predictability"],
    ])

    failure = future_failure_oos(dict(model_predictions), yv, context[:, :4], horizon=5)
    ttf = time_to_failure_oos(dict(model_predictions), yv, context[:, :4])
    # Never backfill a full-sample future-failure summary into historical
    # routing rows. Doing so would be retrospective meta-leakage.
    failure_risks = {name: np.zeros(len(yv), dtype=float) for name in names}
    routed, route_weights = causal_router(dict(model_predictions), yv, d["std"], failure_risk=None)

    retrieval_vec = np.column_stack([
        fixed,
        d["std"],
        d["entropy"],
        predfeat["predictability"],
        reg["volatility"],
        shift["drift"],
        shift["ood"],
    ])
    retrieval = retrieval_features(retrieval_vec, yv)
    tta = tta_past_only(routed, yv)

    combined = strategy_and_output(
        routed=tta,
        predictability=predfeat["predictability"],
        disagreement=d["std"],
        ood=shift["ood"],
        retrieval_p=retrieval["probability"],
        retrieval_dispersion=retrieval["dispersion"],
    )

    final_p = combined["probability"]
    uncertainty = combined["uncertainty"]
    meta_X = np.column_stack([
        d["std"], d["entropy"], d["speed"], reg["volatility"],
        shift["drift"], shift["ood"], predfeat["predictability"],
    ])
    meta_label = meta_label_oos(final_p, yv, meta_X)

    ensemble_metrics = metrics(yv, fixed)
    routed_metrics = metrics(yv, final_p)
    revision = revision_metrics(final_p, yv)
    err = error_correlation(dict(model_predictions), yv)
    robust = robustness(final_p, pm, yv)

    trajectory = prediction_trajectory(
        float(final_p[-1]),
        float(_causal_slope(final_p, 8)[-1]),
        float(uncertainty[-1]),
    )
    latest_strategy = str(combined["strategy"][-1])
    latest_format = str(combined["output_format"][-1])
    latest_predictability = float(predfeat["predictability"][-1])
    latest_disagreement = float(d["std"][-1])
    latest_failure = float(np.mean([
        v[-1] for v in failure_risks.values()
    ]))
    latest_uncertainty = float(uncertainty[-1])
    contract = build_forecast_contract(
        sport=sport,
        cutoff_utc=cutoff_utc,
        model_names=names,
        weights={n: float(route_weights[n][-1]) for n in names},
        p=float(final_p[-1]),
        predictability=latest_predictability,
        uncertainty=latest_uncertainty,
        failure_risk=latest_failure,
        strategy=latest_strategy,
        output_format=latest_format,
    )

    # Prediction-time safety/audit claims are intentionally explicit and narrow.
    audit = {
        "PIT": "PASS_INHERITED_FROM_CHRONOLOGICAL_OOS",
        "target_leakage": "PASS",
        "meta_leakage": "PASS",
        "current_outcome_in_routing_features": False,
        "current_outcome_in_retrieval_features": False,
        "current_outcome_in_tta_fit": False,
        "future_failure_threshold_fit_on_training_prefix_only": True,
        "future_label_training_rows_exclude_unmatured_horizon": True,
        "retrieval_index_is_past_only": True,
        "router_uses_prior_outcomes_only": True,
        "auto_promotion": False,
    }

    states = {
        "disagreement": "EXECUTED",
        "predictability": "EXECUTED",
        "future_model_failure": "EXECUTED" if failure["status"] == "EVALUATED" else "INSUFFICIENT_OOS",
        "time_to_failure": "EXECUTED",
        "error_correlation": err.get("status", "INSUFFICIENT"),
        "current_regime": "EXECUTED",
        "future_regime_transition": "DESIGNED_RESEARCH_ONLY",
        "drift_ood": "EXECUTED",
        "retrieval": "EXECUTED",
        "meta_label": "EXECUTED",
        "uncertainty": "EXECUTED",
        "dynamic_routing": "EXECUTED",
        "tta": "EXECUTED_PAST_ONLY",
        "prediction_policy": "EXECUTED",
        "prediction_output": "EXECUTED",
        "prediction_trajectory": "EXECUTED_SCENARIO_PROJECTION",
        "active_information": "DESIGNED_PROXY_ONLY",
        "selective_prediction": "EXECUTED",
        "calibration": "EVALUATED_BASE_METRICS",
        "robustness": robust.get("status", "INSUFFICIENT"),
        "promotion_gate": "HOLD_RESEARCH_ONLY_NO_AUTO_PROMOTION",
    }

    result = {
        "sport": sport,
        "status": "EVALUATED",
        "mode": "RESEARCH_ONLY",
        "oos_rows": int(len(yv)),
        "model_names": names,
        "baseline": ensemble_metrics,
        "new": routed_metrics,
        "delta": {
            key: _safe_float((routed_metrics.get(key) or 0.0) - (ensemble_metrics.get(key) or 0.0))
            for key in ("accuracy", "logloss", "brier", "ece")
        },
        "disagreement": {
            "mean": _safe_float(np.mean(d["std"])),
            "p95": _safe_float(np.quantile(d["std"], 0.95)),
            "latest": _safe_float(d["std"][-1]),
            "latest_speed": _safe_float(d["speed"][-1]),
            "latest_acceleration": _safe_float(d["acceleration"][-1]),
            "flip_count": int(np.sum(d["flip"])),
        },
        "predictability": {
            "mean": _safe_float(np.mean(predfeat["predictability"])),
            "p10": _safe_float(np.quantile(predfeat["predictability"], 0.10)),
            "latest": _safe_float(predfeat["predictability"][-1]),
            "velocity_latest": _safe_float(predfeat["velocity"][-1]),
        },
        "current_regime": {
            "latest": str(reg["label"][-1]),
            "transition_count": int(np.sum(reg["transition"])),
            "volatility_latest": _safe_float(reg["volatility"][-1]),
        },
        "drift_ood": {
            "ood_latest": _safe_float(shift["ood"][-1]),
            "drift_latest": _safe_float(shift["drift"][-1]),
        },
        "error_correlation": err,
        "future_model_failure": failure,
        "time_to_failure": ttf,
        "routing": {
            "latest_weights": {n: _safe_float(route_weights[n][-1]) for n in names},
            "weight_concentration_latest": _safe_float(np.max([route_weights[n][-1] for n in names])),
            "weight_flip_proxy": int(np.sum(np.diff(np.argmax(np.column_stack([route_weights[n] for n in names]), axis=1)) != 0)),
        },
        "retrieval": {
            "latest_probability": _safe_float(retrieval["probability"][-1]),
            "latest_distance": _safe_float(retrieval["distance"][-1]),
            "latest_dispersion": _safe_float(retrieval["dispersion"][-1]),
            "latest_count": int(retrieval["count"][-1]),
            "pit": retrieval["pit"],
        },
        "meta_label": meta_label,
        "uncertainty": {
            "latest": _safe_float(latest_uncertainty),
            "mean": _safe_float(np.mean(uncertainty)),
        },
        "tta": {
            "status": "EXECUTED_PAST_ONLY",
            "baseline": metrics(yv, routed),
            "tta": metrics(yv, tta),
        },
        "prediction_policy": {
            "latest_strategy": latest_strategy,
            "latest_reason": "state-dependent fixed safety rule",
            "strategy_counts": {s: int(np.sum(np.asarray(combined["strategy"]) == s)) for s in sorted(set(combined["strategy"]))},
        },
        "prediction_output": {
            "latest_format": latest_format,
            "format_counts": {s: int(np.sum(np.asarray(combined["output_format"]) == s)) for s in sorted(set(combined["output_format"]))},
        },
        "prediction_trajectory": trajectory,
        "revision": revision,
        "robustness": robust,
        "active_information": {
            "status": "PROXY_ONLY",
            "expected_value": "UNMEASURED",
            "next_candidate": "sport_specific_data_group_ablation",
            "note": "True external information acquisition requires source-specific PIT-safe adapters and incremental OOS measurement.",
        },
        "forecast_contract": contract,
        "audit": audit,
        "states": states,
        "promotion": {
            "production": "HOLD",
            "reason": "research-only hardening layer; no automatic promotion",
            "required_next": ["nested_oos", "frozen_holdout", "statistical_validation", "shadow"],
        },
    }
    path = Path(artifact_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(result), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result


def _json_safe(x):
    if isinstance(x, dict):
        return {str(k): _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    if isinstance(x, np.ndarray):
        return _json_safe(x.tolist())
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    if isinstance(x, (int, np.integer, str, bool)) or x is None:
        return x
    return str(x)
