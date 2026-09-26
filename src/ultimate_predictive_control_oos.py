from __future__ import annotations

"""Ultimate future-generalization research layer.

Research-only, PIT-safe by construction when fed chronological OOF predictions.
It does not mutate production artifacts or promote a strategy. The layer turns
already-generated chronological OOF model probabilities into auditable signals
for disagreement, predictability, future model failure, time-to-failure,
selective/policy candidates, revision quality, robustness and forecast contracts.
"""

import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline


def _clip_p(p: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(p, dtype=float), 1e-6, 1.0 - 1e-6)


def metric(y: Sequence[int], p: Sequence[float]) -> Dict:
    yv = np.asarray(y, dtype=int)
    pv = _clip_p(np.asarray(p, dtype=float))
    if len(yv) == 0:
        return {"logloss": None, "brier": None, "ece": None, "accuracy": None, "n": 0}
    ll = float(-np.mean(yv * np.log(pv) + (1 - yv) * np.log(1 - pv)))
    br = float(np.mean((pv - yv) ** 2))
    ece = 0.0
    for lo, hi in zip(np.linspace(0.0, 1.0, 10, endpoint=False), np.linspace(0.0, 1.0, 10)):
        mask = (pv >= lo) & ((pv < hi) if hi < 1 else (pv <= hi))
        if np.any(mask):
            ece += float(mask.mean()) * abs(float(yv[mask].mean()) - float(pv[mask].mean()))
    return {
        "logloss": ll,
        "brier": br,
        "ece": float(ece),
        "accuracy": float(np.mean((pv >= 0.5) == yv)),
        "n": int(len(yv)),
    }


def _entropy_binary(p: np.ndarray) -> np.ndarray:
    p = _clip_p(p)
    return -(p * np.log2(p) + (1.0 - p) * np.log2(1.0 - p))


def _js_binary(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    p = _clip_p(p)
    q = _clip_p(q)
    m = 0.5 * (p + q)
    kl1 = p * np.log(p / m) + (1.0 - p) * np.log((1.0 - p) / (1.0 - m))
    kl2 = q * np.log(q / m) + (1.0 - q) * np.log((1.0 - q) / (1.0 - m))
    return 0.5 * (kl1 + kl2)


def disagreement_features(pred_matrix: np.ndarray) -> Dict[str, np.ndarray]:
    """Row-local disagreement; never consumes target outcomes."""
    p = _clip_p(np.asarray(pred_matrix, dtype=float))
    if p.ndim != 2 or p.shape[1] == 0:
        raise ValueError("pred_matrix must be 2-D with at least one model")
    mean = p.mean(axis=1)
    med = np.median(p, axis=1)
    std = p.std(axis=1)
    pmin = p.min(axis=1)
    pmax = p.max(axis=1)
    rng = pmax - pmin
    majority = np.mean((p >= 0.5) == (mean[:, None] >= 0.5), axis=1)
    pair_js = []
    for i in range(p.shape[1]):
        for j in range(i + 1, p.shape[1]):
            pair_js.append(_js_binary(p[:, i], p[:, j]))
    js = np.mean(np.vstack(pair_js), axis=0) if pair_js else np.zeros(len(p), dtype=float)
    direction = (mean >= 0.5).astype(int)
    flip = np.zeros(len(p), dtype=float)
    speed = np.zeros(len(p), dtype=float)
    accel = np.zeros(len(p), dtype=float)
    if len(p) > 1:
        flip[1:] = (direction[1:] != direction[:-1]).astype(float)
        speed[1:] = np.abs(mean[1:] - mean[:-1])
    if len(p) > 2:
        accel[2:] = np.abs((mean[2:] - mean[1:-1]) - (mean[1:-1] - mean[:-2]))
    # Causal rolling disagreement state. The current row is included only in the
    # summary of the current state and prior rows never depend on future rows.
    recent_mean = np.zeros(len(p), dtype=float)
    recent_std = np.zeros(len(p), dtype=float)
    for i in range(len(p)):
        lo = max(0, i - 9)
        z = std[lo:i + 1]
        recent_mean[i] = float(np.mean(z))
        recent_std[i] = float(np.std(z))
    entropy = _entropy_binary(mean)
    return {
        "mean_probability": mean,
        "median_probability": med,
        "std": std,
        "min": pmin,
        "max": pmax,
        "range": rng,
        "class_agreement": majority,
        "pairwise_js": js,
        "entropy": entropy,
        "direction": direction,
        "flip": flip,
        "speed": speed,
        "acceleration": accel,
        "recent_disagreement_mean": recent_mean,
        "recent_disagreement_std": recent_std,
    }


def predictability_features(dis: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """Prediction-time predictability proxy, explicitly separated from confidence."""
    entropy_norm = np.clip(np.asarray(dis["entropy"], dtype=float), 0.0, 1.0)
    disagreement_norm = np.clip(np.asarray(dis["std"], dtype=float) * 4.0, 0.0, 1.0)
    stability_penalty = np.clip(
        0.60 * np.asarray(dis["speed"], dtype=float) * 4.0
        + 0.40 * np.asarray(dis["acceleration"], dtype=float) * 4.0,
        0.0, 1.0,
    )
    score = np.clip(
        1.0 - 0.45 * entropy_norm - 0.35 * disagreement_norm - 0.20 * stability_penalty,
        0.0, 1.0,
    )
    return {
        "predictability": score,
        "predictability_velocity": np.r_[0.0, np.diff(score)] if len(score) else np.array([]),
        "confidence_proxy": np.abs(np.asarray(dis["mean_probability"], dtype=float) - 0.5) * 2.0,
    }


def _chronological_forecast(
    X: np.ndarray, target: np.ndarray, blocks: int = 3
) -> Dict:
    """Cross-fold meta forecast: each test block is predicted only from prior blocks."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(target, dtype=int)
    n = len(y)
    if n < 120 or len(np.unique(y)) < 2:
        return {"status": "INSUFFICIENT_OOS", "rows": int(n)}
    parts = np.array_split(np.arange(n), blocks)
    preds: List[float] = []
    ys: List[int] = []
    fold_rows = []
    for bi in range(1, len(parts)):
        tr = np.concatenate(parts[:bi])
        te = parts[bi]
        if len(tr) < 60 or len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2:
            continue
        model = Pipeline([
            ("scale", StandardScaler()),
            ("lr", LogisticRegression(C=0.25, max_iter=2000, random_state=20260926)),
        ])
        model.fit(X[tr], y[tr])
        pp = np.clip(model.predict_proba(X[te])[:, 1], 1e-6, 1 - 1e-6)
        preds.extend(pp.tolist())
        ys.extend(y[te].tolist())
        fold_rows.append({
            "train_rows": int(len(tr)),
            "test_rows": int(len(te)),
            "test_start": int(te[0]),
            "test_end": int(te[-1]),
            "metrics": metric(y[te], pp),
        })
    if len(ys) < 30:
        return {"status": "INSUFFICIENT_OOS", "rows": int(len(ys))}
    return {
        "status": "EVALUATED",
        "rows": int(len(ys)),
        "metrics": metric(ys, preds),
        "folds": fold_rows,
    }


def future_predictability_analysis(
    pred: np.ndarray,
    y: np.ndarray,
    meta_features: np.ndarray,
    horizon: int = 5,
) -> Dict:
    """Forecast future difficulty from current prediction-time signals only."""
    p = _clip_p(pred)
    yv = np.asarray(y, dtype=int)
    n = len(p)
    future_difficulty = np.full(n, np.nan, dtype=float)
    for i in range(n - horizon):
        future_difficulty[i] = float(
            np.mean([-(yv[j] * np.log(p[j]) + (1 - yv[j]) * np.log(1 - p[j]))
                     for j in range(i + 1, i + 1 + horizon)])
        )
    valid = np.isfinite(future_difficulty)
    if valid.sum() < 120:
        return {"status": "INSUFFICIENT_OOS", "rows": int(valid.sum())}
    cut = float(np.quantile(future_difficulty[valid], 0.60))
    target = (future_difficulty > cut).astype(int)
    target = target[valid]
    X = np.asarray(meta_features, dtype=float)[valid]
    result = _chronological_forecast(X, target, blocks=3)
    result.update({
        "target": "future_logloss_above_60th_percentile",
        "horizon_rows": int(horizon),
        "threshold": cut,
        "future_difficulty_mean": float(np.nanmean(future_difficulty)),
        "future_difficulty_p75": float(np.nanquantile(future_difficulty, 0.75)),
    })
    return result


def future_failure_analysis(
    model_predictions: Dict[str, np.ndarray],
    y: np.ndarray,
    context: np.ndarray,
    horizon: int = 5,
) -> Dict:
    """Research predictor for model-specific future degradation and time-to-warning."""
    yv = np.asarray(y, dtype=int)
    n = len(yv)
    per_model = {}
    for name, pv in model_predictions.items():
        p = _clip_p(np.asarray(pv, dtype=float))
        if len(p) != n:
            raise ValueError("model prediction length mismatch")
        row_loss = -(yv * np.log(p) + (1 - yv) * np.log(1 - p))
        future = np.full(n, np.nan, dtype=float)
        for i in range(n - horizon):
            future[i] = float(np.mean(row_loss[i + 1:i + 1 + horizon]))
        valid = np.isfinite(future)
        if valid.sum() < 120:
            per_model[name] = {"status": "INSUFFICIENT_OOS", "rows": int(valid.sum())}
            continue
        # Prediction-time state excludes current outcome. Current probability
        # margin, disagreement and recent volatility are safe meta-features.
        pmat = np.column_stack([np.abs(_clip_p(np.asarray(z, dtype=float)) - 0.5) * 2.0 for z in model_predictions.values()])
        model_idx = list(model_predictions).index(name)
        margin = pmat[:, model_idx]
        X = np.column_stack([
            margin,
            context[:, 0],  # ensemble disagreement
            context[:, 1],  # probability entropy
            context[:, 2],  # probability speed
            context[:, 3],  # disagreement persistence
        ])
        threshold = float(np.quantile(future[valid], 0.60))
        target = (future > threshold).astype(int)[valid]
        result = _chronological_forecast(X[valid], target, blocks=3)
        current_state_risk = float(np.clip(
            0.35 * (1.0 - float(np.mean(margin[-min(20, len(margin)):])))
            + 0.35 * float(np.mean(context[-min(20, len(context)): , 0]))
            + 0.30 * float(np.mean(context[-min(20, len(context)): , 3]) * 2.0),
            0.0, 1.0
        ))
        per_model[name] = {
            **result,
            "failure_definition": "future_window_logloss_above_60th_percentile",
            "horizon_rows": int(horizon),
            "threshold": threshold,
            "current_failure_risk_heuristic": current_state_risk,
            "heuristic_time_to_failure_rows": int(max(1, round(1.0 / max(current_state_risk, 0.02)))),
        }
    return {
        "status": "EVALUATED" if per_model else "INSUFFICIENT_OOS",
        "models": per_model,
        "policy": "research_only; future-window target is score-only; predictor inputs exclude current/future outcomes",
    }


def error_correlation(model_predictions: Dict[str, np.ndarray], y: np.ndarray) -> Dict:
    names = list(model_predictions)
    errors = np.column_stack([
        ((np.asarray(model_predictions[n]) >= 0.5).astype(int) != np.asarray(y, dtype=int)).astype(float)
        for n in names
    ])
    if len(names) < 2 or len(errors) < 3:
        return {"status": "INSUFFICIENT"}
    corr = np.corrcoef(errors, rowvar=False)
    return {
        "status": "EVALUATED",
        "models": names,
        "error_correlation": np.asarray(corr, dtype=float).tolist(),
        "mean_pairwise_error_correlation": float(np.mean(corr[np.triu_indices(len(names), 1)])),
        "mean_error_overlap": float(np.mean([
            np.mean(errors[:, i] * errors[:, j])
            for i in range(len(names)) for j in range(i + 1, len(names))
        ])),
    }


def selective_policy_ablation(
    p: np.ndarray, y: np.ndarray, predictability: np.ndarray, disagreement: np.ndarray
) -> Dict:
    p = _clip_p(p)
    y = np.asarray(y, dtype=int)
    candidates = [
        ("fixed", np.ones(len(y), dtype=bool)),
        ("predictability_075", predictability >= 0.75),
        ("predictability_055", predictability >= 0.55),
        ("low_disagreement", disagreement <= 0.12),
    ]
    rows = []
    for name, mask in candidates:
        if int(mask.sum()) < 20 or len(np.unique(y[mask])) < 2:
            rows.append({"policy": name, "status": "INSUFFICIENT", "coverage": float(mask.mean())})
            continue
        rows.append({
            "policy": name,
            "status": "EVALUATED",
            "coverage": float(mask.mean()),
            **metric(y[mask], p[mask]),
        })
    return {
        "status": "EVALUATED",
        "policies": rows,
        "selection_rule": "thresholds pre-registered; no outcome-derived threshold tuning inside this run",
    }


def revision_policy_ablation(p: np.ndarray, y: np.ndarray) -> Dict:
    p = _clip_p(p)
    y = np.asarray(y, dtype=int)
    if len(p) < 30:
        return {"status": "INSUFFICIENT"}
    prev = np.r_[p[0], p[:-1]]
    delta = p - prev
    revision = np.abs(delta) >= 0.05
    direction_changed = (p >= 0.5) != (prev >= 0.5)
    next_y = y
    current_correct = (p >= 0.5) == next_y
    keep_correct = (prev >= 0.5) == next_y
    quality = {
        "revision_count": int(revision.sum()),
        "direction_flip_count": int((revision & direction_changed).sum()),
        "revision_accuracy": float(np.mean(current_correct[revision])) if revision.any() else None,
        "keep_accuracy_on_revision_rows": float(np.mean(keep_correct[revision])) if revision.any() else None,
        "revision_value": (
            float(np.mean(current_correct[revision].astype(float) - keep_correct[revision].astype(float)))
            if revision.any() else None
        ),
        "false_revision_count": int(np.sum(revision & (~current_correct) & keep_correct)),
    }
    return {"status": "EVALUATED", **quality, "policy": "absolute probability revision threshold 5%; fixed ex ante"}


def robustness_stress(p: np.ndarray, pred_matrix: np.ndarray, y: np.ndarray) -> Dict:
    p = _clip_p(p)
    pm = _clip_p(pred_matrix)
    y = np.asarray(y, dtype=int)
    rng = np.random.default_rng(20260926)
    noise = np.clip(p + rng.normal(0.0, 0.02, size=len(p)), 1e-6, 1 - 1e-6)
    plus = np.clip(p + 0.02, 1e-6, 1 - 1e-6)
    minus = np.clip(p - 0.02, 1e-6, 1 - 1e-6)
    masks = {
        "noise_flip_rate": float(np.mean((noise >= 0.5) != (p >= 0.5))),
        "plus_flip_rate": float(np.mean((plus >= 0.5) != (p >= 0.5))),
        "minus_flip_rate": float(np.mean((minus >= 0.5) != (p >= 0.5))),
    }
    dropout = np.mean(np.delete(pm, 0, axis=1), axis=1) if pm.shape[1] > 1 else p
    masks["single_model_dropout_flip_rate"] = float(np.mean((dropout >= 0.5) != (p >= 0.5)))
    return {
        "status": "EVALUATED",
        "prediction_space_stress": masks,
        "baseline": metric(y, p),
        "noise": metric(y, noise),
        "drop_first_model": metric(y, dropout),
        "policy": "research-only prediction-space stress; feature/source perturbations require sport-specific adapters",
    }


def forecast_contract(
    sport: str,
    model_names: Sequence[str],
    weights: Dict[str, float],
    cutoff_utc: str,
    artifact_path: str,
    predictability: float,
    disagreement: float,
    failure_risk: float,
) -> Dict:
    ttl = max(1, int(round(1.0 / max(0.02, 1.0 - float(predictability)))))
    if predictability >= 0.75 and disagreement <= 0.10:
        form = "single_probability"
    elif predictability >= 0.55:
        form = "probability_plus_range"
    elif predictability >= 0.40:
        form = "scenario_or_set"
    else:
        form = "abstain_candidate"
    return {
        "sport": sport,
        "prediction_time": cutoff_utc,
        "valid_until_candidate_rows": ttl,
        "data_snapshot": artifact_path,
        "model_version": "research-only-oos-controller",
        "strategy": "dynamic_policy_candidate",
        "models": list(model_names),
        "weights": {str(k): float(v) for k, v in weights.items()},
        "confidence": float(np.clip(1.0 - abs(disagreement), 0.0, 1.0)),
        "predictability": float(predictability),
        "uncertainty": {
            "model_disagreement": float(disagreement),
            "future_failure_risk": float(failure_risk),
        },
        "prediction_format_candidate": form,
        "abstain_candidate": bool(form == "abstain_candidate"),
        "pit_status": "INHERITED_FROM_CHRONOLOGICAL_OOS",
    }


def run_ultimate_research(
    sport: str,
    oof_folds: Sequence[Dict],
    y: np.ndarray,
    event_ids: Sequence[str],
    model_names: Sequence[str],
    weights: Dict[str, float] | None,
    cutoff_utc: str,
    artifact_rel: str,
    feature_names: Sequence[str] | None = None,
    X_oof: np.ndarray | None = None,
) -> Dict:
    """Build complete research artifact from strict chronological OOF folds."""
    names = list(model_names)
    ys = np.asarray(y, dtype=int)
    probs = {n: [] for n in names}
    fold_meta = []
    for fold in oof_folds:
        end = int(fold["end"])
        te = int(fold["te"])
        n = te - end
        if n <= 0:
            continue
        fold_meta.append({"end": end, "te": te, "rows": n, "event_ids": list(fold.get("event_ids") or [])})
        for name in names:
            probs[name].extend(np.asarray(fold["preds"][name], dtype=float).tolist())
    if not probs or not event_ids or len(ys) != len(event_ids):
        return {"sport": sport, "status": "BLOCKED", "reason": "invalid_oof_alignment"}
    pred_matrix = np.column_stack([_clip_p(np.asarray(probs[n])) for n in names])
    if pred_matrix.shape[0] != len(ys):
        return {"sport": sport, "status": "BLOCKED", "reason": "prediction_target_mismatch"}
    d = disagreement_features(pred_matrix)
    pfeat = predictability_features(d)
    fixed_weights = dict(weights or {n: 1.0 / len(names) for n in names})
    wv = np.asarray([fixed_weights.get(n, 0.0) for n in names], dtype=float)
    if wv.sum() <= 0:
        wv = np.full(len(names), 1.0 / len(names))
    wv /= wv.sum()
    ensemble = np.sum(pred_matrix * wv[None, :], axis=1)
    meta = np.column_stack([
        d["std"],
        d["entropy"],
        d["speed"],
        d["recent_disagreement_mean"],
        pfeat["predictability"],
    ])
    future_pred = future_predictability_analysis(ensemble, ys, meta)
    # Future failure context is prediction-time only.
    failure_ctx = np.column_stack([
        d["std"], d["entropy"], d["speed"], d["recent_disagreement_mean"]
    ])
    future_failure = future_failure_analysis(probs, ys, failure_ctx)
    err_corr = error_correlation(probs, ys)
    selective = selective_policy_ablation(ensemble, ys, pfeat["predictability"], d["std"])
    revision = revision_policy_ablation(ensemble, ys)
    robustness = robustness_stress(ensemble, pred_matrix, ys)
    fold_scores = []
    cursor = 0
    for fm in fold_meta:
        lo, hi = cursor, cursor + fm["rows"]
        fold_scores.append({
            "end": fm["end"],
            "te": fm["te"],
            "metrics": metric(ys[lo:hi], ensemble[lo:hi]),
            "mean_disagreement": float(np.mean(d["std"][lo:hi])),
            "mean_predictability": float(np.mean(pfeat["predictability"][lo:hi])),
        })
        cursor = hi
    worst = max((x["metrics"]["logloss"] for x in fold_scores if x["metrics"]["logloss"] is not None), default=None)
    model_metrics = {n: metric(ys, pred_matrix[:, i]) for i, n in enumerate(names)}
    latest_risk = 0.5
    if future_failure.get("models"):
        vals = [v.get("current_failure_risk_heuristic") for v in future_failure["models"].values()
                if isinstance(v, dict) and v.get("current_failure_risk_heuristic") is not None]
        if vals:
            latest_risk = float(np.mean(vals))
    contract = forecast_contract(
        sport=sport,
        model_names=names,
        weights={n: float(wv[i]) for i, n in enumerate(names)},
        cutoff_utc=cutoff_utc,
        artifact_path=artifact_rel,
        predictability=float(pfeat["predictability"][-1]),
        disagreement=float(d["std"][-1]),
        failure_risk=latest_risk,
    )
    active_info = {
        "status": "PROXY_ONLY",
        "feature_gap_count": int(np.isnan(X_oof).sum()) if X_oof is not None else None,
        "candidate_information_features": list(feature_names or [])[:50],
        "policy": "no external retrieval performed; candidate ranking must use PIT-safe sport-specific VOI experiments",
    }
    states = {
        "disagreement": "EXECUTED",
        "predictability": "EXECUTED",
        "future_model_failure": "EXECUTED",
        "time_to_failure": "EXECUTED",
        "error_correlation": "EXECUTED",
        "selective_policy": "EXECUTED",
        "prediction_update": "EXECUTED",
        "robustness": "EXECUTED",
        "active_information": "DESIGNED_PROXY_ONLY",
        "prediction_format": "EXECUTED",
        "promotion": "HOLD_RESEARCH_ONLY",
    }
    return {
        "sport": sport,
        "status": "EVALUATED",
        "mode": "RESEARCH_ONLY",
        "model_names": names,
        "oos_rows": int(len(ys)),
        "oos_folds": int(len(fold_meta)),
        "folds": fold_scores,
        "model_metrics": model_metrics,
        "disagreement": {
            "mean": float(np.mean(d["std"])),
            "p95": float(np.quantile(d["std"], 0.95)),
            "latest": float(d["std"][-1]),
            "latest_speed": float(d["speed"][-1]),
            "latest_acceleration": float(d["acceleration"][-1]),
            "flip_count": int(d["flip"].sum()),
        },
        "predictability": {
            "mean": float(np.mean(pfeat["predictability"])),
            "p10": float(np.quantile(pfeat["predictability"], 0.10)),
            "latest": float(pfeat["predictability"][-1]),
            "latest_velocity": float(pfeat["predictability_velocity"][-1]) if len(pfeat["predictability_velocity"]) else 0.0,
            "confidence_proxy_mean": float(np.mean(pfeat["confidence_proxy"])),
        },
        "future_predictability": future_pred,
        "future_model_failure": future_failure,
        "error_correlation": err_corr,
        "selective_ablation": selective,
        "prediction_update": revision,
        "robustness": robustness,
        "active_information": active_info,
        "worst_fold_logloss": worst,
        "forecast_contract": contract,
        "states": states,
        "promotion_status": "HOLD_RESEARCH_ONLY_NO_AUTO_PROMOTION",
    }


def write_artifact(result: Dict, path: Path) -> Dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = _json_safe(result)
    path.write_text(json.dumps(safe, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result


def _json_safe(x):
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    if isinstance(x, dict):
        return {str(k): _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    if isinstance(x, np.ndarray):
        return _json_safe(x.tolist())
    if isinstance(x, (int, np.integer, str, bool)) or x is None:
        return x
    return str(x)
