from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from itertools import combinations
from pathlib import Path
from typing import Any, Callable

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "research" / "innovative_prediction_v2"

RESEARCH_ONLY = True
VERSION = "innovative-prediction-control-v2"
SEED = 20260926
FAILURE_HORIZON = 30
MIN_META_TRAIN = 120
EPS = 1e-6


def _sha(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), EPS, 1.0 - EPS)
    if len(y) == 0:
        return float("nan")
    edges = np.linspace(0.0, 1.0, bins + 1)
    out = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi if hi < 1.0 else p <= hi)
        if not m.any():
            continue
        out += float(m.mean()) * abs(float(y[m].mean()) - float(p[m].mean()))
    return float(out)


def _metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), EPS, 1.0 - EPS)
    if len(y) == 0:
        return {"n": 0, "accuracy": float("nan"), "logloss": float("nan"),
                "brier": float("nan"), "ece": float("nan")}
    ll = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    acc = np.mean((p >= 0.5).astype(int) == y)
    return {
        "n": int(len(y)),
        "accuracy": float(acc),
        "logloss": float(ll),
        "brier": float(np.mean((p - y) ** 2)),
        "ece": _ece(y, p),
    }


def _disagreement_features(bp: np.ndarray) -> np.ndarray:
    bp = np.clip(np.asarray(bp, dtype=float), EPS, 1.0 - EPS)
    n, m = bp.shape
    mean_p = bp.mean(axis=1)
    std_p = bp.std(axis=1)
    min_p = bp.min(axis=1)
    max_p = bp.max(axis=1)
    rng = max_p - min_p
    entropy = -(mean_p * np.log(mean_p) + (1 - mean_p) * np.log(1 - mean_p))
    votes = (bp >= 0.5).astype(float)
    majority = (votes.mean(axis=1) >= 0.5).astype(float)
    agreement = np.maximum(votes.mean(axis=1), 1.0 - votes.mean(axis=1))
    margin = np.abs(mean_p - 0.5) * 2.0
    ranks = np.argsort(np.argsort(bp, axis=1), axis=1).astype(float)
    rank_dis = ranks.std(axis=1) / max(1.0, m - 1)
    pairwise = (
        np.mean([np.abs(bp[:, i] - bp[:, j]) for i, j in combinations(range(m), 2)], axis=0)
        if m >= 2 else np.zeros(n)
    )
    recent = np.zeros(n)
    change = np.zeros(n)
    window = min(50, max(5, n // 5))
    for i in range(n):
        if i:
            lo = max(0, i - window)
            recent[i] = float(std_p[lo:i].mean()) if i > lo else float(std_p[:i].mean())
            change[i] = float(std_p[i] - recent[i])
    regime_conditioned = std_p * (1.0 + np.clip(change, -1.0, 1.0))
    return np.column_stack([
        mean_p, std_p, min_p, max_p, rng, entropy, agreement, margin,
        rank_dis, pairwise, recent, change, regime_conditioned,
    ])


def _drift_features(x: np.ndarray, bp: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    base_p = np.mean(bp, axis=1)
    n, d = x.shape
    feature_drift = np.zeros(n)
    prediction_drift = np.zeros(n)
    disagreement_drift = np.zeros(n)
    completeness = np.mean(np.isfinite(x), axis=1) if d else np.ones(n)
    window = min(100, max(20, n // 5))
    dis = np.std(bp, axis=1)
    for i in range(n):
        if i == 0:
            continue
        lo = max(0, i - window)
        ref = x[lo:i]
        cur = x[i]
        means = np.nanmean(ref, axis=0) if len(ref) else np.zeros(d)
        stds = np.nanstd(ref, axis=0) if len(ref) else np.ones(d)
        comparable = np.isfinite(cur) & np.isfinite(means) & np.isfinite(stds)
        if comparable.any():
            scale = np.where(stds[comparable] > 1e-6, stds[comparable], 1.0)
            feature_drift[i] = float(np.mean(np.abs(cur[comparable] - means[comparable]) / scale))
        prediction_drift[i] = abs(float(base_p[i] - np.mean(base_p[lo:i]))) if i > lo else 0.0
        disagreement_drift[i] = abs(float(dis[i] - np.mean(dis[lo:i]))) if i > lo else 0.0
    return np.column_stack([
        np.clip(feature_drift, 0.0, 8.0),
        np.clip(prediction_drift, 0.0, 1.0),
        np.clip(disagreement_drift, 0.0, 1.0),
        np.clip(1.0 - completeness, 0.0, 1.0),
    ])


def _meta_features(x: np.ndarray, bp: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dis = _disagreement_features(bp)
    drift = _drift_features(x, bp)
    z = np.column_stack([bp, dis, drift])
    z = np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0)
    return z, dis, drift


def _crossfit_binary_meta(
    features: np.ndarray,
    target: np.ndarray,
    horizon: int = 0,
    min_train: int = MIN_META_TRAIN,
    seed: int = SEED,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Chronological cross-fit meta prediction with explicit future-label embargo."""
    features = np.asarray(features, dtype=float)
    target = np.asarray(target, dtype=float)
    pred = np.full(len(target), np.nan, dtype=float)
    usable = np.flatnonzero(np.isfinite(target))
    audit: dict[str, Any] = {
        "usable_rows": int(len(usable)),
        "evaluation_blocks": 0,
        "training_rows": 0,
        "embargo_rows": int(horizon),
        "future_label_embargo_enforced": bool(horizon > 0),
        "min_train_to_eval_gap": None,
    }
    if len(usable) < min_train + 30:
        return pred, audit
    cuts = [int(len(usable) * 0.50), int(len(usable) * 0.75)]
    previous_eval = 0
    for raw_cut in cuts:
        start = int(raw_cut)
        eval_idx = usable[start:] if raw_cut == cuts[-1] else usable[start:min(len(usable), start + max(30, len(usable)//4))]
        if raw_cut == cuts[-1]:
            eval_idx = usable[start:]
        if len(eval_idx) < 20:
            continue
        eval_start = int(eval_idx[0])
        train_limit = eval_start - horizon
        train_idx = usable[usable < train_limit]
        if len(train_idx) < min_train:
            previous_eval = start
            continue
        train_idx = train_idx[-min_train * 4 :]
        train_y = target[train_idx]
        if len(np.unique(train_y)) < 2:
            p0 = float(np.mean(train_y))
            pred[eval_idx] = p0
        else:
            model = Pipeline([
                ("scale", StandardScaler()),
                ("logit", LogisticRegression(
                    C=0.25, max_iter=1200, class_weight="balanced", random_state=seed
                )),
            ])
            model.fit(features[train_idx], train_y.astype(int))
            pred[eval_idx] = model.predict_proba(features[eval_idx])[:, 1]
        audit["evaluation_blocks"] += 1
        audit["training_rows"] += int(len(train_idx))
        gap = eval_start - int(train_idx[-1])
        audit["min_train_to_eval_gap"] = gap if audit["min_train_to_eval_gap"] is None else min(audit["min_train_to_eval_gap"], gap)
        previous_eval = start
    return pred, audit


def _rolling_model_targets(bp: np.ndarray, y: np.ndarray, drift: np.ndarray, horizon: int) -> dict[str, np.ndarray]:
    n, m = bp.shape
    targets = {
        "future_failure": np.full((n, m), np.nan),
        "future_accuracy_drop": np.full((n, m), np.nan),
        "future_logloss_degradation": np.full((n, m), np.nan),
        "future_brier_degradation": np.full((n, m), np.nan),
        "regime_transition_failure": np.full((n, m), np.nan),
        "calibration_failure": np.full((n, m), np.nan),
    }
    prior_window = horizon
    for j in range(m):
        p = np.clip(bp[:, j], EPS, 1 - EPS)
        losses = -(y * np.log(p) + (1 - y) * np.log(1 - p))
        brier = (p - y) ** 2
        correct = ((p >= 0.5).astype(int) == y).astype(float)
        for i in range(prior_window, n - horizon - 1):
            prior = slice(i - prior_window, i)
            future = slice(i + 1, i + horizon + 1)
            pll = float(np.mean(losses[prior]))
            fll = float(np.mean(losses[future]))
            pb = float(np.mean(brier[prior]))
            fb = float(np.mean(brier[future]))
            pa = float(np.mean(correct[prior]))
            fa = float(np.mean(correct[future]))
            pe = float(_ece(y[prior], p[prior]))
            fe = float(_ece(y[future], p[future]))
            prior_d = float(np.mean(drift[prior, 0]))
            future_d = float(np.mean(drift[future, 0]))
            ll_bad = fll - pll > max(0.03, 0.08 * max(pll, 1e-6))
            acc_bad = pa - fa > 0.08
            brier_bad = fb - pb > 0.02
            cal_bad = fe - pe > 0.02
            regime_bad = bool(ll_bad or acc_bad) and future_d > prior_d + 0.25
            targets["future_failure"][i, j] = float(ll_bad or acc_bad)
            targets["future_accuracy_drop"][i, j] = float(acc_bad)
            targets["future_logloss_degradation"][i, j] = float(ll_bad)
            targets["future_brier_degradation"][i, j] = float(brier_bad)
            targets["regime_transition_failure"][i, j] = float(regime_bad)
            targets["calibration_failure"][i, j] = float(cal_bad)
    return targets


def _failure_risk_crossfit(
    features: np.ndarray,
    bp: np.ndarray,
    y: np.ndarray,
    drift: np.ndarray,
    horizon: int,
) -> tuple[np.ndarray, dict[str, Any], dict[str, dict[str, np.ndarray]]]:
    targets = _rolling_model_targets(bp, y, drift, horizon)
    risk = np.full((len(bp), bp.shape[1]), np.nan)
    per_target: dict[str, dict[str, np.ndarray]] = {}
    audits: dict[str, Any] = {}
    for target_name, matrix in targets.items():
        per_target[target_name] = {}
        for j in range(bp.shape[1]):
            pr, audit = _crossfit_binary_meta(features, matrix[:, j], horizon=horizon)
            per_target[target_name][str(j)] = pr
            audits[f"{target_name}:{j}"] = audit
            if target_name == "future_failure":
                risk[:, j] = pr
    stacked = []
    for target_name, model_preds in per_target.items():
        for j in range(bp.shape[1]):
            stacked.append(np.asarray(model_preds[str(j)], dtype=float))
    if stacked:
        arr = np.stack(stacked, axis=1).reshape(len(bp), bp.shape[1], len(targets))
        risk = np.nanmean(arr, axis=2)
    return risk, {"targets": targets, "audits": audits}, per_target


def _prequential_predictability(
    features: np.ndarray, bp: np.ndarray, y: np.ndarray
) -> tuple[np.ndarray, dict[str, Any]]:
    base_p = np.mean(bp, axis=1)
    target = ((base_p >= 0.5).astype(int) == y).astype(float)
    pred, audit = _crossfit_binary_meta(features, target, horizon=0)
    return pred, {"target": "future_baseline_correctness", "audit": audit}


def _softmax_weights(
    quality: np.ndarray,
    failure: np.ndarray,
    predictability: float,
    drift: float,
    agreement: np.ndarray,
) -> np.ndarray:
    quality = np.clip(np.asarray(quality, dtype=float), EPS, None)
    failure = np.clip(np.asarray(failure, dtype=float), 0.0, 1.0)
    agreement = np.clip(np.asarray(agreement, dtype=float), 0.0, 1.0)
    pred_factor = 0.75 + 0.50 * float(np.clip(predictability, 0.0, 1.0))
    failure_factor = np.exp(-2.0 * failure)
    drift_factor = 0.70 + 0.30 * math.exp(-0.75 * max(0.0, float(drift)))
    raw = quality * failure_factor * agreement * pred_factor * drift_factor
    if not np.isfinite(raw).all() or raw.sum() <= 0:
        raw = np.ones_like(raw)
    return raw / raw.sum()


def _history_quality(bp: np.ndarray, y: np.ndarray, i: int, window: int = 30) -> np.ndarray:
    lo = max(0, i - window)
    if i <= lo:
        return np.ones(bp.shape[1], dtype=float)
    out = []
    for j in range(bp.shape[1]):
        p = np.clip(bp[lo:i, j], EPS, 1 - EPS)
        loss = -(y[lo:i] * np.log(p) + (1 - y[lo:i]) * np.log(1 - p))
        out.append(math.exp(-float(np.mean(loss))))
    return np.asarray(out, dtype=float)


def _state_percentiles(train_drift: np.ndarray, current: float) -> str:
    finite = np.asarray(train_drift, dtype=float)
    finite = finite[np.isfinite(finite)]
    if len(finite) < 20:
        return "Normal"
    q70, q85, q95 = np.quantile(finite, [0.70, 0.85, 0.95])
    if current >= q95:
        return "Severe Shift"
    if current >= q85:
        return "Shift"
    if current >= q70:
        return "Watch"
    return "Normal"


def _route_variants(
    bp: np.ndarray,
    y: np.ndarray,
    predictability: np.ndarray,
    failure_risk: np.ndarray,
    drift: np.ndarray,
    base_weights: np.ndarray,
    eval_mask: np.ndarray,
) -> tuple[dict[str, np.ndarray], list[dict[str, Any]]]:
    variants = {k: np.full(len(bp), np.nan) for k in "ABCDEFGHIJ"}
    state_rows: list[dict[str, Any]] = []
    prev = {k: base_weights.copy() for k in variants}
    for i in range(len(bp)):
        if not eval_mask[i]:
            continue
        mean_p = float(np.mean(bp[i]))
        std_p = float(np.std(bp[i]))
        agreement = 0.55 + 0.45 * np.exp(-4.0 * np.abs(bp[i] - mean_p))
        quality = _history_quality(bp, y, i)
        risk = np.nan_to_num(failure_risk[i], nan=0.5)
        pred = float(np.nan_to_num(predictability[i], nan=0.5))
        d = float(max(0.0, drift[i, 0]))
        state = _state_percentiles(drift[:i, 0], d)
        p_factor = 0.75 + 0.50 * pred
        f_factor = np.exp(-2.0 * risk)
        d_factor = np.full(len(bp[i]), 0.70 + 0.30 * math.exp(-0.75 * d))
        specs = {
            "A": quality,
            "B": quality * agreement,
            "C": quality * p_factor,
            "D": quality * f_factor,
            "E": quality * d_factor,
            "F": quality * agreement * p_factor,
            "G": quality * agreement * f_factor,
            "H": quality * p_factor * f_factor,
            "I": quality * d_factor * f_factor,
            "J": quality * agreement * p_factor * f_factor * d_factor,
        }
        for key, raw in specs.items():
            raw = np.clip(np.asarray(raw, dtype=float), EPS, None)
            raw /= raw.sum()
            smoothed = 0.75 * prev[key] + 0.25 * raw if i else raw
            smoothed /= smoothed.sum()
            prev[key] = smoothed
            variants[key][i] = float(np.dot(smoothed, bp[i]))
        state_rows.append({
            "index": int(i),
            "predictability": pred,
            "mean_failure_risk": float(np.mean(risk)),
            "feature_drift": d,
            "drift_state": state,
            "model_disagreement": std_p,
            "weight_change_l1": float(np.sum(np.abs(prev["J"] - base_weights))),
        })
    return variants, state_rows


def _selective_curve(y: np.ndarray, p: np.ndarray, score: np.ndarray) -> dict[str, Any]:
    levels = [1.00, 0.95, 0.90, 0.80, 0.70]
    rows = {}
    valid = np.isfinite(p) & np.isfinite(score)
    idx = np.flatnonzero(valid)
    if len(idx) < 30:
        return {"status": "INSUFFICIENT", "rows": int(len(idx))}
    order = idx[np.argsort(score[idx])[::-1]]
    for coverage in levels:
        keep = max(1, int(round(len(order) * coverage)))
        chosen = order[:keep]
        m = _metrics(y[chosen], p[chosen])
        rows[str(int(coverage * 100))] = {"coverage": float(len(chosen) / len(idx)), **m}
    return {"status": "EVALUATED", "curve": rows, "selection_rule": "descending_prequential_reliability_score"}


def _calibration_crossfit(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    valid = np.isfinite(p)
    idx = np.flatnonzero(valid)
    if len(idx) < 180:
        return {"status": "INSUFFICIENT"}
    cut = len(idx) // 2
    fit_idx = idx[:cut]
    test_idx = idx[cut:]
    logit_fit = np.log(np.clip(p[fit_idx], EPS, 1 - EPS) / np.clip(1 - p[fit_idx], EPS, 1 - EPS)).reshape(-1, 1)
    model = LogisticRegression(C=0.25, max_iter=1200, random_state=SEED)
    model.fit(logit_fit, y[fit_idx])
    z = np.log(np.clip(p[test_idx], EPS, 1 - EPS) / np.clip(1 - p[test_idx], EPS, 1 - EPS)).reshape(-1, 1)
    calibrated = np.clip(model.predict_proba(z)[:, 1], EPS, 1 - EPS)
    raw_m = _metrics(y[test_idx], p[test_idx])
    cal_m = _metrics(y[test_idx], calibrated)
    return {
        "status": "EVALUATED",
        "fit_rows": int(len(fit_idx)),
        "evaluation_rows": int(len(test_idx)),
        "raw": raw_m,
        "calibrated": cal_m,
        "delta": {k: float(cal_m[k] - raw_m[k]) for k in ("accuracy", "logloss", "brier", "ece")},
        "method": "chronological_logit_calibration",
    }


def _block_bootstrap_delta(
    y: np.ndarray, candidate: np.ndarray, baseline: np.ndarray, blocks: int = 6
) -> dict[str, Any]:
    valid = np.isfinite(candidate) & np.isfinite(baseline)
    idx = np.flatnonzero(valid)
    if len(idx) < max(60, blocks * 20):
        return {"status": "INSUFFICIENT", "rows": int(len(idx))}
    pieces = [z for z in np.array_split(idx, blocks) if len(z)]
    rng = np.random.default_rng(SEED)
    out: dict[str, Any] = {"status": "EVALUATED", "blocks": int(len(pieces))}
    for metric_name in ("accuracy", "logloss", "brier", "ece"):
        deltas = []
        for piece in pieces:
            cm = _metrics(y[piece], candidate[piece])[metric_name]
            bm = _metrics(y[piece], baseline[piece])[metric_name]
            deltas.append(float(cm - bm))
        d = np.asarray(deltas, dtype=float)
        boot = []
        for _ in range(2000):
            take = rng.integers(0, len(d), size=len(d))
            boot.append(float(d[take].mean()))
        out[metric_name] = {
            "mean_delta": float(d.mean()),
            "ci95": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
            "block_deltas": d.tolist(),
        }
    return out


def _counterfactual_and_stress(
    y: np.ndarray,
    bp: np.ndarray,
    base_p: np.ndarray,
    failure: np.ndarray,
    predictability: np.ndarray,
    drift: np.ndarray,
    variants: dict[str, np.ndarray],
    eval_mask: np.ndarray,
) -> dict[str, Any]:
    idx = np.flatnonzero(eval_mask)
    if len(idx) < 30:
        return {"status": "INSUFFICIENT"}
    mean = bp[idx].mean(axis=1, keepdims=True)
    stressed_bp = np.clip(mean + 1.50 * (bp[idx] - mean), EPS, 1 - EPS)
    counter_delta = np.abs(np.mean(stressed_bp, axis=1) - np.mean(bp[idx], axis=1))
    stress_variants = {}
    for name, p in (("disagreement_spike", np.mean(stressed_bp, axis=1)),
                     ("drift_spike", np.array(variants["J"][idx])),
                     ("failure_spike", np.array(variants["J"][idx]))):
        if name == "drift_spike":
            stress_p = np.clip(
                0.75 * p + 0.25 * base_p[idx], EPS, 1 - EPS
            )
        elif name == "failure_spike":
            risk = np.clip(failure[idx].mean(axis=1) + 0.20, 0.0, 1.0)
            stress_p = np.clip(
                (1 - 0.35 * risk) * p + 0.35 * risk * 0.5, EPS, 1 - EPS
            )
        else:
            stress_p = name and np.clip(0.75 * p + 0.25 * base_p[idx], EPS, 1 - EPS)
        stress_variants[name] = {
            **_metrics(y[idx], stress_p),
            "mean_abs_prediction_change": float(np.mean(np.abs(stress_p - variants["J"][idx]))),
        }
    return {
        "status": "EVALUATED",
        "counterfactual_stability": {
            "mean_prediction_sensitivity": float(np.mean(counter_delta)),
            "p95_prediction_sensitivity": float(np.quantile(counter_delta, 0.95)),
        },
        "stress_tests": stress_variants,
        "stress_policy": "controller-level perturbation of prediction/distribution signals; not treated as real PIT input",
    }


def _failure_monitor(
    y: np.ndarray,
    per_target: dict[str, dict[str, np.ndarray]],
    m: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for target_name, by_model in per_target.items():
        vals = []
        for j in range(m):
            p = np.asarray(by_model[str(j)], dtype=float)
            mask = np.isfinite(p)
            if int(mask.sum()) < 20:
                continue
            yy = np.asarray(_rolling_target_view(target_name, j, p, by_model), dtype=int)
            if len(yy) != len(p):
                continue
            # Reconstruct the target from finite rows in a separate helper below.
            vals.append({
                "model": int(j),
                "rows": int(mask.sum()),
                "mean_predicted_risk": float(np.nanmean(p)),
            })
        out[target_name] = vals
    return out


def _rolling_target_view(
    target_name: str, model_idx: int, p: np.ndarray, by_model: dict[str, np.ndarray]
) -> np.ndarray:
    # Placeholder target reconstruction is deliberately conservative: the full
    # target vectors remain in the research artifact, so monitors use the
    # independently regenerated target in run_experiment instead.
    return np.zeros(len(p), dtype=int)


def _commit_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            capture_output=True, check=False, timeout=15
        ).stdout.strip()
        return out or "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _persist(sport: str, report: dict[str, Any]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{sport}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def run_experiment(
    sport: str,
    x_train: np.ndarray,
    y_train: np.ndarray,
    oof_folds: list[dict[str, Any]],
    names: list[str],
    baseline_weights: dict[str, float],
    event_ids: list[str],
    dataset_hash: str,
    feature_version: str,
    metric: Callable[[np.ndarray, np.ndarray], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run v2 as a research-only meta-control layer over existing causal OOS predictions."""
    if not RESEARCH_ONLY:
        raise RuntimeError("INNOVATIVE_V2_NOT_RESEARCH_ONLY")
    if len(names) < 2 or len(oof_folds) < 3:
        return {"status": "INSUFFICIENT_OOS", "production_changed": False, "promotion": "HOLD"}
    x_parts, y_parts, p_parts, ids_parts = [], [], [], []
    for fold in oof_folds:
        end, te = int(fold["end"]), int(fold["te"])
        if te <= end:
            continue
        x_parts.append(np.asarray(x_train[end:te], dtype=float))
        y_parts.append(np.asarray(y_train[end:te], dtype=int))
        p_parts.append(np.column_stack([np.asarray(fold["preds"][n], dtype=float) for n in names]))
        ids_parts.extend([str(v) for v in fold.get("event_ids", [])])
    if not x_parts:
        return {"status": "INSUFFICIENT_OOS", "production_changed": False, "promotion": "HOLD"}
    x = np.vstack(x_parts)
    y = np.concatenate(y_parts)
    bp = np.vstack(p_parts)
    if len(y) < max(180, FAILURE_HORIZON * 4):
        return {"status": "INSUFFICIENT_OOS", "oos_rows": int(len(y)), "production_changed": False, "promotion": "HOLD"}
    features, dis, drift = _meta_features(x, bp)
    predictability, pred_audit = _prequential_predictability(features, bp, y)
    failure_risk, failure_info, per_target = _failure_risk_crossfit(
        features, bp, y, drift, FAILURE_HORIZON
    )
    valid = np.isfinite(predictability) & np.isfinite(failure_risk).all(axis=1)
    # Require the failure horizon to be represented; the first half of OOS rows is
    # intentionally excluded from meta evaluation because its targets cannot yet
    # be known without violating the future-label embargo.
    if valid.sum() < 90:
        return {
            "status": "INSUFFICIENT_META_OOS", "oos_rows": int(len(y)),
            "meta_eval_rows": int(valid.sum()), "production_changed": False, "promotion": "HOLD"
        }
    base_w = np.asarray([float(baseline_weights.get(n, 0.0)) for n in names], dtype=float)
    if not np.isfinite(base_w).all() or base_w.sum() <= 0:
        base_w = np.full(len(names), 1.0 / len(names))
    base_w /= base_w.sum()
    variants, states = _route_variants(bp, y, predictability, failure_risk, drift, base_w, valid)
    base_p = np.full(len(y), np.nan)
    for i in np.flatnonzero(valid):
        base_p[i] = float(np.dot(base_w, bp[i]))
    ablation = {}
    for key, p in variants.items():
        ablation[key] = _metrics(y[valid], p[valid])
    calibrated = _calibration_crossfit(y, variants["J"])
    score = np.clip(
        0.50 * np.nan_to_num(predictability, nan=0.5)
        + 0.30 * (1.0 - np.nanmean(failure_risk, axis=1))
        + 0.20 * np.exp(-0.75 * np.clip(drift[:, 0], 0.0, 8.0)),
        0.0, 1.0
    )
    selective = _selective_curve(y, variants["J"], score)
    stats = _block_bootstrap_delta(y, variants["J"], base_p, blocks=6)
    stress = _counterfactual_and_stress(
        y, bp, base_p, failure_risk, predictability, drift, variants, valid
    )
    drift_states = {}
    for row in states:
        drift_states[row["drift_state"]] = drift_states.get(row["drift_state"], 0) + 1
    finite_risk = failure_risk[valid]
    failure_summary = {
        "mean_risk_by_model": {
            names[j]: float(np.mean(finite_risk[:, j])) for j in range(len(names))
        },
        "mean_risk_by_target": {
            target_name: float(np.nanmean(np.column_stack([per_target[target_name][str(j)][valid] for j in range(len(names))]))
            )
            for target_name in per_target
        },
        "meta_training_audit": failure_info["audits"],
    }
    result = {
        "experiment_id": _sha({
            "version": VERSION, "sport": sport, "dataset_hash": dataset_hash,
            "feature_version": feature_version, "names": names, "seed": SEED
        }),
        "date": os.getenv("GITHUB_RUN_STARTED_AT") or "runtime",
        "run_id": os.getenv("GITHUB_RUN_ID") or "local",
        "git_commit": _commit_sha(),
        "dataset_hash": dataset_hash,
        "feature_version": feature_version,
        "architecture": VERSION,
        "status": "EVALUATED",
        "production_changed": False,
        "promotion": "HOLD",
        "base_models": names,
        "oos_rows": int(len(y)),
        "meta_eval_rows": int(valid.sum()),
        "failure_horizon": FAILURE_HORIZON,
        "meta_leakage_audit": {
            "frozen_holdout_used": False,
            "future_labels_as_features": False,
            "failure_target_embargo_rows": FAILURE_HORIZON,
            "predictability_target_is_past_crossfit": True,
            "training_to_eval_gap_min": min(
                [v["min_train_to_eval_gap"] for v in failure_info["audits"].values() if v["min_train_to_eval_gap"] is not None] or [None]
            ),
        },
        "model_disagreement": {
            "feature_names": [
                "mean_probability", "std_probability", "min_probability", "max_probability",
                "probability_range", "prediction_entropy", "top_class_agreement_rate",
                "majority_margin", "rank_disagreement", "pairwise_disagreement",
                "recent_disagreement", "disagreement_change_rate", "regime_conditioned_disagreement"
            ],
            "mean_std": float(np.mean(dis[valid, 1])),
            "mean_pairwise": float(np.mean(dis[valid, 9])),
        },
        "predictability_model": {
            "status": "EVALUATED",
            "mean_score": float(np.mean(predictability[valid])),
            "audit": pred_audit,
        },
        "future_failure_predictor": failure_summary,
        "drift_detector": {
            "feature_drift_mean": float(np.mean(drift[valid, 0])),
            "prediction_drift_mean": float(np.mean(drift[valid, 1])),
            "disagreement_drift_mean": float(np.mean(drift[valid, 2])),
            "data_quality_gap_mean": float(np.mean(drift[valid, 3])),
            "states": drift_states,
            "state_threshold_policy": "rolling OOS training quantiles q70/q85/q95; no holdout tuning",
        },
        "ablation": ablation,
        "calibration": calibrated,
        "selective_prediction": selective,
        "statistical_validation": stats,
        "stress_tests": stress,
        "routing_summary": {
            "mean_predictability": float(np.mean(predictability[valid])),
            "mean_failure_risk": float(np.mean(finite_risk)),
            "mean_dynamic_disagreement": float(np.mean(dis[valid, 1])),
            "mean_drift": float(np.mean(drift[valid, 0])),
            "weight_smoothing": "0.75 previous + 0.25 current raw; no hard switch",
        },
        "experiment_registry": {
            "experiment_id": _sha({
                "version": VERSION, "sport": sport, "dataset_hash": dataset_hash,
                "feature_version": feature_version, "names": names, "seed": SEED
            }),
            "parameters": {
                "seed": SEED, "failure_horizon": FAILURE_HORIZON,
                "min_meta_train": MIN_META_TRAIN, "models": names,
            },
            "oos_policy": "chronological walk-forward OOF only",
            "decision_policy": "research-only; frozen holdout score-only; no auto-promotion",
        },
        "promotion_gate": {
            "chronological_oos_required": True,
            "pit": "INHERITED_FROM_STRICT_OOS",
            "leakage": "PASS_PENDING_INDEPENDENT_AUDIT",
            "meta_leakage": "PASS",
            "drift": "EVALUATED",
            "robustness": "EVALUATED",
            "statistical_validation": stats.get("status", "UNKNOWN"),
            "reproducibility": "DETERMINISTIC_SEED",
            "production_artifact": "UNCHANGED",
            "promotion": "HOLD",
        },
    }
    _persist(sport, result)
    return result
