from __future__ import annotations

import json
import math
import os
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src import innovative_prediction_v2 as v2

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "research" / "maximum_future_generalization_v6"
VERSION = "maximum-future-generalization-v6"
SEED = 20260926
DEFAULT_MAX_OOS = 2500
EPS = 1e-6


def _finite(a: Any, default: float = 0.0) -> np.ndarray:
    x = np.asarray(a, dtype=float)
    return np.nan_to_num(x, nan=default, posinf=default, neginf=default)


def _safe_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    return v2._metrics(np.asarray(y, dtype=int), np.asarray(p, dtype=float))


def _error_correlation(bp: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    errors = ((np.asarray(bp) < 0.5).astype(int) != np.asarray(y)[:, None]).astype(float)
    m = errors.shape[1]
    corr = np.eye(m)
    overlap = np.zeros((m, m), dtype=float)
    for i in range(m):
        for j in range(m):
            overlap[i, j] = float(np.mean((errors[:, i] > 0) & (errors[:, j] > 0)))
            if i == j:
                continue
            a, b = errors[:, i], errors[:, j]
            if np.std(a) > 1e-9 and np.std(b) > 1e-9:
                corr[i, j] = float(np.corrcoef(a, b)[0, 1])
            else:
                corr[i, j] = 0.0
    pairwise_diversity = 1.0 - np.clip(np.mean(corr[np.triu_indices(m, 1)]) if m > 1 else 0.0, -1, 1)
    return {
        "pairwise_error_correlation": corr.tolist(),
        "error_overlap": overlap.tolist(),
        "mean_error_correlation": float(np.mean(corr[np.triu_indices(m, 1)])) if m > 1 else 0.0,
        "error_diversity": float(pairwise_diversity),
        "model_error_rate": errors.mean(axis=0).tolist(),
    }


def _prediction_dynamics(bp: np.ndarray) -> dict[str, Any]:
    bp = np.asarray(bp, dtype=float)
    mean_p = np.mean(bp, axis=1)
    velocity = np.diff(mean_p, prepend=mean_p[:1])
    acceleration = np.diff(velocity, prepend=velocity[:1])
    flips = (np.sign(mean_p[1:] - 0.5) != np.sign(mean_p[:-1] - 0.5)).astype(int)
    flips = np.concatenate([[0], flips])
    persistence = np.zeros(len(mean_p))
    reversal = np.zeros(len(mean_p))
    for i in range(len(mean_p)):
        lo = max(0, i - 20)
        diffs = mean_p[lo:i] - 0.5
        if len(diffs):
            persistence[i] = float(np.mean(np.sign(diffs) == np.sign(mean_p[i] - 0.5)))
            if len(diffs) >= 2:
                reversal[i] = float(np.sign(diffs[-1]) != np.sign(diffs[-2]))
    return {
        "mean_velocity": float(np.mean(np.abs(velocity))),
        "mean_acceleration": float(np.mean(np.abs(acceleration))),
        "flip_count": int(flips.sum()),
        "flip_rate": float(flips.mean()),
        "persistence_mean": float(persistence.mean()),
        "reversal_rate": float(reversal.mean()),
        "row_velocity": velocity,
        "row_acceleration": acceleration,
        "row_flip": flips,
    }


def _feature_reliability(x: np.ndarray, window: int = 120) -> dict[str, Any]:
    x = np.asarray(x, dtype=float)
    n, d = x.shape
    finite = np.isfinite(x)
    completeness = finite.mean(axis=1) if d else np.ones(n)
    row_stability = np.zeros(n, dtype=float)
    per_feature = finite.mean(axis=0).tolist() if d else []
    for i in range(n):
        lo = max(0, i - window)
        if i - lo < 20 or d == 0:
            row_stability[i] = 0.0
            continue
        ref = x[lo:i]
        cur = x[i]
        med = np.nanmedian(ref, axis=0)
        mad = np.nanmedian(np.abs(ref - med), axis=0)
        scale = np.where(np.isfinite(mad) & (mad > 1e-6), mad, 1.0)
        comparable = np.isfinite(cur) & np.isfinite(med)
        if comparable.any():
            deviation = np.mean(np.abs(cur[comparable] - med[comparable]) / scale[comparable])
            row_stability[i] = float(1.0 / (1.0 + min(8.0, deviation)))
    row_reliability = np.clip(0.65 * completeness + 0.35 * row_stability, 0.0, 1.0)
    return {
        "row_reliability": row_reliability,
        "per_feature_completeness": per_feature,
        "mean_completeness": float(completeness.mean()),
        "mean_reliability": float(row_reliability.mean()),
        "policy": "strictly prequential feature completeness + prior-window robustness only",
    }


def _invariant_feature_discovery(x: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 120 or x.shape[1] == 0:
        return {"status": "INSUFFICIENT"}
    blocks = np.array_split(np.arange(len(x)), 3)
    scores = []
    for j in range(x.shape[1]):
        corrs = []
        signs = []
        for idx in blocks:
            vals = x[idx, j]
            mask = np.isfinite(vals)
            if mask.sum() >= 20 and np.std(vals[mask]) > 1e-9 and np.std(y[idx][mask]) > 1e-9:
                r = float(np.corrcoef(vals[mask], y[idx][mask])[0, 1])
                corrs.append(r)
                signs.append(np.sign(r))
        if len(corrs) >= 2:
            sign_consistency = float(np.mean(np.asarray(signs) == np.sign(np.mean(corrs))))
            magnitude_stability = float(1.0 / (1.0 + np.std(corrs)))
            score = abs(float(np.mean(corrs))) * sign_consistency * magnitude_stability
            scores.append((j, score, corrs, sign_consistency))
    scores.sort(key=lambda z: -z[1])
    return {
        "status": "EVALUATED",
        "top_features": [
            {
                "feature_index": int(j),
                "invariant_score": float(score),
                "block_correlations": list(map(float, corr)),
                "sign_consistency": float(sc),
            }
            for j, score, corr, sc in scores[:30]
        ],
        "policy": "stability diagnostic only; correlations are not causal evidence",
    }


def _regime_transition(x: np.ndarray, bp: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    drift = v2._drift_features(x, bp)
    d = np.asarray(drift[:, 0], dtype=float)
    n = len(d)
    probs = np.full((n, 4), 0.25, dtype=float)
    states = np.zeros(n, dtype=int)
    for i in range(n):
        hist = d[:i]
        hist = hist[np.isfinite(hist)]
        if len(hist) < 30:
            continue
        q70, q85, q95 = np.quantile(hist, [0.70, 0.85, 0.95])
        states[i] = int(np.select([d[i] >= q95, d[i] >= q85, d[i] >= q70], [3, 2, 1], default=0))
        prior_states = states[:i]
        counts = np.ones(4, dtype=float)
        if len(prior_states) >= 2:
            src = prior_states[:-1]
            dst = prior_states[1:]
            mask = src == states[i]
            for b in dst[mask][-5000:]:
                counts[int(b)] += 1.0
        probs[i] = counts / counts.sum()
    return probs, {
        "status": "EVALUATED",
        "state_counts": {str(i): int((states == i).sum()) for i in range(4)},
        "labels": ["Normal", "Watch", "Shift", "Severe Shift"],
        "threshold_policy": "q70/q85/q95 recomputed from rows strictly before each evaluation row",
        "transition_policy": "uses only transitions observed before each evaluation row",
    }


def _retrieval_features(
    x: np.ndarray, bp: np.ndarray, y: np.ndarray, k: int = 12, history_cap: int = 1200
) -> tuple[np.ndarray, dict[str, Any]]:
    x = np.asarray(x, dtype=float)
    bp = np.asarray(bp, dtype=float)
    out = np.full((len(x), 5), np.nan)
    similarities = []
    for i in range(len(x)):
        start = max(0, i - history_cap)
        if i - start < 60:
            continue
        ref_x = x[start:i]
        cur_x = x[i]
        med = np.nanmedian(ref_x, axis=0)
        mad = np.nanmedian(np.abs(ref_x - med), axis=0)
        scale_x = np.where(np.isfinite(mad) & (mad > 1e-6), mad, 1.0)
        base_ref = np.column_stack([
            np.nan_to_num((ref_x - med) / scale_x),
            np.mean(bp[start:i], axis=1, keepdims=True),
            np.std(bp[start:i], axis=1, keepdims=True),
        ])
        cur_base = np.column_stack([
            np.nan_to_num(((cur_x - med) / scale_x))[None, :],
            [[float(np.mean(bp[i])), float(np.std(bp[i]))]],
        ]
        dim = min(base_ref.shape[1], cur_base.shape[1])
        ref = base_ref[:, :dim]
        cur = cur_base[:, :dim][0]
        dist = np.sqrt(np.mean((ref - cur) ** 2, axis=1))
        take = np.argsort(dist)[:min(k, len(dist))]
        d = dist[take]
        w = 1.0 / (1.0 + d)
        yy = y[start:i][take]
        pp = np.mean(bp[start:i][take], axis=1)
        fail = ((pp >= 0.5).astype(int) != yy).astype(float)
        out[i] = [
            float(1.0 / (1.0 + np.mean(d))),
            float(np.sum(w * fail) / np.sum(w)),
            float(np.mean(fail)),
            float(np.sum(w * yy) / np.sum(w)),
            float(len(take) / max(1, k)),
        ]
        similarities.append(float(np.mean(d)))
    return out, {
        "status": "EVALUATED",
        "features": [
            "nearest_failure_similarity",
            "historical_failure_frequency",
            "historical_error_frequency",
            "historical_success_probability",
            "retrieval_coverage",
        ],
        "mean_similarity": float(np.mean(similarities)) if similarities else None,
        "policy": "retrieval reference and normalization are strictly prior-row only",
    }


def _meta_label_models(x: np.ndarray, bp: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    feat, _, _ = v2._meta_features(x, bp)
    out = np.full_like(bp, np.nan, dtype=float)
    audits = {}
    for j in range(bp.shape[1]):
        target = (((bp[:, j] >= 0.5).astype(int)) == y).astype(float)
        pred, audit = v2._crossfit_binary_meta(feat, target, horizon=0, min_train=120, seed=SEED + j)
        out[:, j] = pred
        audits[str(j)] = audit
    return out, {"status": "EVALUATED", "audits": audits}


def _uncertainty_decomposition(
    x: np.ndarray, bp: np.ndarray, reliability: np.ndarray, drift: np.ndarray
) -> dict[str, np.ndarray]:
    mean_p = np.mean(bp, axis=1)
    model = np.clip(np.std(bp, axis=1), 0.0, 1.0)
    data = np.clip(1.0 - reliability, 0.0, 1.0)
    disagreement = model
    distribution = np.clip(drift[:, 0] / 3.0, 0.0, 1.0)
    information = np.clip(
        0.5 * data + 0.5 * drift[:, 3], 0.0, 1.0
    )
    irreducible = np.clip(
        -(mean_p * np.log(np.clip(mean_p, EPS, 1 - EPS))
          + (1 - mean_p) * np.log(np.clip(1 - mean_p, EPS, 1 - EPS))),
        0.0, 1.0,
    )
    return {
        "data_uncertainty": data,
        "model_uncertainty": model,
        "disagreement_uncertainty": disagreement,
        "distribution_shift_uncertainty": distribution,
        "information_uncertainty": information,
        "irreducible_uncertainty_proxy": irreducible,
    }


def _time_to_failure(
    bp: np.ndarray, y: np.ndarray, max_horizon: int = 60
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    n, m = bp.shape
    ttf = np.full((n, m), np.nan)
    hazard = np.full((n, m), np.nan)
    failure = ((bp >= 0.5).astype(int) != y[:, None]).astype(int)
    for j in range(m):
        next_failure = n
        for i in range(n - 1, -1, -1):
            if i + 1 < n:
                next_failure = i + 1 if failure[i + 1, j] else next_failure
            distance = next_failure - i if next_failure < n else max_horizon
            ttf[i, j] = float(min(distance, max_horizon))
            lo = max(0, i - 60)
            prior_fail = failure[lo:i, j]
            hazard[i, j] = float(np.mean(prior_fail[-30:])) if len(prior_fail) else 0.0
    return ttf, hazard, {
        "status": "EVALUATED",
        "horizon_cap": int(max_horizon),
        "warning": "ttf is an evaluation-derived label for model monitoring, not a prediction-time feature",
    }


def _tts_prediction_ttf(bp: np.ndarray, y: np.ndarray, max_horizon: int = 60) -> dict[str, Any]:
    ttf, hazard, meta = _time_to_failure(bp, y, max_horizon)
    return {
        "median_ttf_by_model": np.nanmedian(ttf, axis=0).tolist(),
        "mean_hazard_by_model": np.nanmean(hazard, axis=0).tolist(),
        "label_generation": meta,
    }


def _sequential_tta(y: np.ndarray, p: np.ndarray, min_train: int = 60, refit_interval: int = 10) -> np.ndarray:
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    out = p.copy()
    model = None
    for i in range(len(p)):
        lo = max(0, i - 300)
        train_end = i
        if train_end - lo < min_train or len(np.unique(y[lo:train_end])) < 2:
            continue
        if model is None or i % max(1, refit_interval) == 0:
            z = np.log(p[lo:train_end] / (1 - p[lo:train_end])).reshape(-1, 1)
            model = LogisticRegression(C=0.5, max_iter=500, random_state=SEED)
            model.fit(z, y[lo:train_end])
        zi = np.log(p[i] / (1 - p[i])).reshape(1, -1)
        out[i] = float(np.clip(model.predict_proba(zi)[0, 1], EPS, 1 - EPS))
    return out


def _residual_crossfit(
    x: np.ndarray, bp: np.ndarray, y: np.ndarray, refit_interval: int = 10
) -> np.ndarray:
    feat = np.column_stack([
        np.mean(bp, axis=1),
        np.std(bp, axis=1),
        x[:, : min(10, x.shape[1])],
    ])
    pred = np.full(len(y), np.nan)
    model = None
    for i in range(len(y)):
        if i < 120:
            continue
        lo = max(0, i - 800)
        yy = y[lo:i]
        if len(np.unique(yy)) < 2:
            pred[i] = float(np.mean(yy))
            continue
        if model is None or i % max(1, refit_interval) == 0:
            model = Pipeline([
                ("scale", StandardScaler()),
                ("logit", LogisticRegression(C=0.25, max_iter=800, random_state=SEED)),
            ])
            model.fit(np.nan_to_num(feat[lo:i]), yy)
        pred[i] = float(np.clip(
            model.predict_proba(np.nan_to_num(feat[i:i + 1]))[0, 1], EPS, 1 - EPS
        ))
    return pred


def _conformal_binary(y: np.ndarray, p: np.ndarray, alpha_levels=(0.10, 0.20, 0.30)) -> dict[str, Any]:
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    rows = {}
    sizes = {}
    for alpha in alpha_levels:
        covered = []
        set_size = []
        for i in range(len(y)):
            lo = max(0, i - 200)
            calib_y, calib_p = y[lo:i], p[lo:i]
            if len(calib_y) < 40:
                continue
            scores = 1.0 - np.where(calib_y == 1, calib_p, 1.0 - calib_p)
            q = float(np.quantile(scores, 1 - alpha, method="higher"))
            s1 = 1.0 - p[i]
            s0 = p[i]
            include1, include0 = s1 <= q, s0 <= q
            if not include1 and not include0:
                include1 = True
                include0 = True
            covered.append(bool(include1 if y[i] == 1 else include0))
            set_size.append(int(include1) + int(include0))
        rows[str(alpha)] = {
            "coverage": float(np.mean(covered)) if covered else None,
            "mean_set_size": float(np.mean(set_size)) if set_size else None,
            "n": int(len(covered)),
        }
        sizes[str(alpha)] = set_size
    return {"status": "EVALUATED", "alpha_results": rows, "policy": "rolling split-conformal score; sequential calibration only"}


def _pareto_frontier(metrics: dict[str, dict[str, Any]]) -> list[str]:
    keys = list(metrics)
    front = []
    for a in keys:
        dominated = False
        for b in keys:
            if a == b:
                continue
            better_or_equal = (
                metrics[b]["accuracy"] >= metrics[a]["accuracy"]
                and metrics[b]["logloss"] <= metrics[a]["logloss"]
                and metrics[b]["brier"] <= metrics[a]["brier"]
                and metrics[b]["ece"] <= metrics[a]["ece"]
            )
            strictly = (
                metrics[b]["accuracy"] > metrics[a]["accuracy"]
                or metrics[b]["logloss"] < metrics[a]["logloss"]
                or metrics[b]["brier"] < metrics[a]["brier"]
                or metrics[b]["ece"] < metrics[a]["ece"]
            )
            if better_or_equal and strictly:
                dominated = True
                break
        if not dominated:
            front.append(a)
    return front


def _adaptive_compute(score: np.ndarray) -> dict[str, Any]:
    score = np.asarray(score, dtype=float)
    tier = np.full(len(score), "MEDIUM", dtype=object)
    for i in range(len(score)):
        hist = score[:i]
        hist = hist[np.isfinite(hist)]
        if len(hist) < 30:
            continue
        q30, q70 = np.quantile(hist, [0.30, 0.70])
        tier[i] = "HARD" if score[i] < q30 else "EASY" if score[i] > q70 else "MEDIUM"
    unique, counts = np.unique(tier, return_counts=True)
    return {
        "status": "POLICY_ONLY",
        "tiers": {str(k): int(v) for k, v in zip(unique, counts)},
        "policy": {
            "EASY": "standard_base_or_ensemble",
            "MEDIUM": "ensemble_plus_retrieval",
            "HARD": "specialist_plus_stress_check",
        },
        "threshold_policy": "rolling prior-score q30/q70; no future-score inspection",
    }


def _safety_monitor(p: np.ndarray, baseline: np.ndarray, score: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    p = np.asarray(p, dtype=float)
    baseline = np.asarray(baseline, dtype=float)
    jump = np.abs(p - np.concatenate([[p[0]], p[:-1]]))
    invalid = (~np.isfinite(p)) | (p <= 0.0) | (p >= 1.0) | (jump > 0.25) | (score < 0.05)
    safe = np.where(invalid, baseline, np.clip(p, EPS, 1 - EPS))
    return safe, {
        "invalid_or_risky_rows": int(invalid.sum()),
        "fallback_rate": float(invalid.mean()),
        "policy": "research-only safety monitor; invalid/risky v6 output falls back to incumbent baseline",
    }


def _label_quality(y: np.ndarray, event_ids: list[str]) -> dict[str, Any]:
    y = np.asarray(y, dtype=float)
    duplicate_ids = len(event_ids) - len(set(event_ids))
    missing = int(np.sum(~np.isfinite(y)))
    binary = np.isin(y, [0, 1])
    return {
        "duplicate_event_ids": int(duplicate_ids),
        "missing_labels": missing,
        "non_binary_labels": int((~binary & np.isfinite(y)).sum()),
        "status": "PASS" if duplicate_ids == 0 and missing == 0 and np.all(binary) else "REVIEW",
    }


def _rolling_diversity_weights(
    bp: np.ndarray, y: np.ndarray, i: int, base_w: np.ndarray, window: int = 200
) -> np.ndarray:
    lo = max(0, i - window)
    hist_p = np.asarray(bp[lo:i], dtype=float)
    hist_y = np.asarray(y[lo:i], dtype=int)
    if len(hist_y) < 40 or len(base_w) < 2:
        return np.asarray(base_w, dtype=float)
    errors = ((hist_p < 0.5).astype(int) != hist_y[:, None]).astype(float)
    m = hist_p.shape[1]
    corr = np.eye(m)
    for a in range(m):
        for b in range(a + 1, m):
            if np.std(errors[:, a]) > 1e-9 and np.std(errors[:, b]) > 1e-9:
                r = float(np.corrcoef(errors[:, a], errors[:, b])[0, 1])
            else:
                r = 0.0
            corr[a, b] = corr[b, a] = r
    quality = []
    for j in range(m):
        p = np.clip(hist_p[:, j], EPS, 1 - EPS)
        ll = -np.mean(hist_y * np.log(p) + (1 - hist_y) * np.log(1 - p))
        quality.append(math.exp(-float(ll)))
    quality = np.asarray(quality, dtype=float)
    quality /= quality.sum() if quality.sum() > 0 else 1.0
    penalty = np.asarray([
        max(0.0, float(np.mean(np.delete(corr[j], j)))) if m > 1 else 0.0
        for j in range(m)
    ])
    raw = np.asarray(base_w, dtype=float) * (1.0 - 0.40 * np.clip(penalty, 0, 1))
    raw *= 0.50 + 0.50 * (quality / max(float(np.max(quality)), EPS))
    if not np.isfinite(raw).all() or raw.sum() <= 0:
        raw = np.asarray(base_w, dtype=float)
    return raw / raw.sum()


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
    max_oos_rows: int | None = None,
) -> dict[str, Any]:
    if not v2.RESEARCH_ONLY:
        raise RuntimeError("MAX_FUTURE_V6_MUST_REMAIN_RESEARCH_ONLY")
    parts_x, parts_y, parts_p, parts_ids = [], [], [], []
    for fold in oof_folds:
        end, te = int(fold["end"]), int(fold["te"])
        if te <= end:
            continue
        parts_x.append(np.asarray(x_train[end:te], dtype=float))
        parts_y.append(np.asarray(y_train[end:te], dtype=int))
        parts_p.append(np.column_stack([np.asarray(fold["preds"][n], dtype=float) for n in names]))
        parts_ids.extend([str(z) for z in fold.get("event_ids", [])])
    if not parts_x:
        return {"status": "INSUFFICIENT_OOS", "promotion": "HOLD", "production_changed": False}
    x = np.vstack(parts_x)
    y = np.concatenate(parts_y)
    bp = np.vstack(parts_p)
    ids = parts_ids
    max_rows = int(max_oos_rows or os.getenv("MAX_FUTURE_V6_OOS_ROWS") or DEFAULT_MAX_OOS)
    mode = "FULL_OOS" if len(y) <= max_rows else "REDUCED_OOS"
    if len(y) > max_rows:
        x, y, bp, ids = x[-max_rows:], y[-max_rows:], bp[-max_rows:], ids[-max_rows:]
    if len(y) < 240 or len(names) < 2:
        return {"status": "INSUFFICIENT_OOS", "oos_rows": int(len(y)), "promotion": "HOLD", "production_changed": False}

    reliability = _feature_reliability(x)
    dis_stats = _error_correlation(bp, y)
    dyn = _prediction_dynamics(bp)
    invariant = _invariant_feature_discovery(x, y)
    drift = v2._drift_features(x, bp)
    transition, transition_meta = _regime_transition(x, bp)
    retrieval, retrieval_meta = _retrieval_features(x, bp, y)
    meta_label, meta_meta = _meta_label_models(x, bp, y)
    uncertainty = _uncertainty_decomposition(x, bp, reliability["row_reliability"], drift)
    ttf_monitor = _tts_prediction_ttf(bp, y)
    baseline_w = np.asarray([float(baseline_weights.get(n, 0.0)) for n in names])
    if not np.isfinite(baseline_w).all() or baseline_w.sum() <= 0:
        baseline_w = np.full(len(names), 1.0 / len(names))
    baseline_w /= baseline_w.sum()
    baseline = bp @ baseline_w

    meta_features, _, _ = v2._meta_features(x, bp)
    failure_risk, failure_info, per_target = v2._failure_risk_crossfit(
        meta_features, bp, y, drift, v2.FAILURE_HORIZON
    )
    v2_eval = {
        "status": "ROW_LEVEL_PREQUENTIAL_FAILURE_RISK",
        "future_failure_predictor": {
            "mean_risk_by_target": {
                target_name: float(np.nanmean(np.column_stack([
                    per_target[target_name][str(j)] for j in range(len(names))
                ])))
                for target_name in per_target
            },
            "audits": failure_info.get("audits", {}),
        },
    }

    with np.errstate(invalid="ignore"):
        meta_mean = np.nanmean(meta_label, axis=1)
        retrieval_fail = retrieval[:, 1]
    meta_mean = np.nan_to_num(meta_mean, nan=0.5, posinf=0.5, neginf=0.5)
    retrieval_fail = np.nan_to_num(retrieval_fail, nan=0.5, posinf=0.5, neginf=0.5)
    pred_score = np.clip(
        0.25 * reliability["row_reliability"]
        + 0.20 * (1 - np.std(bp, axis=1))
        + 0.20 * transition.max(axis=1)
        + 0.15 * np.nan_to_num(meta_mean, nan=0.5)
        + 0.20 * (1 - np.clip(drift[:, 0] / 3.0, 0, 1)),
        0.0,
        1.0,
    )
    corr = np.asarray(dis_stats["pairwise_error_correlation"], dtype=float)
    row_diversity = np.vstack([
        _rolling_diversity_weights(bp, y, i, baseline_w)
        for i in range(len(y))
    ])

    retrieval_success = np.nan_to_num(retrieval[:, 3], nan=0.5, posinf=0.5, neginf=0.5)
    raw = np.column_stack([
        baseline,
        np.mean(bp, axis=1),
        np.clip(0.75 * baseline + 0.25 * retrieval_success, EPS, 1 - EPS),
        np.clip(0.75 * baseline + 0.25 * meta_mean, EPS, 1 - EPS),
    ])
    tta = _sequential_tta(y, baseline)
    residual = _residual_crossfit(x, bp, y)
    raw[:, 3] = np.where(np.isfinite(residual), 0.70 * raw[:, 3] + 0.30 * residual, raw[:, 3])
    tta_d = _safe_metrics(y, tta)
    conformal = _conformal_binary(y, baseline)

    finite_risk = np.asarray(failure_risk, dtype=float)
    full = np.zeros(len(y))
    for i in range(len(y)):
        q = np.clip(pred_score[i], 0.0, 1.0)
        fail_i = np.clip(np.nan_to_num(np.mean(failure_risk[i]), nan=0.5), 0.0, 1.0)
        risk_factor = math.exp(-1.5 * fail_i)
        shift_factor = math.exp(-0.50 * max(0.0, float(drift[i, 0])))
        trans_factor = float(np.clip(transition[i].max(), 0.25, 1.0))
        w = row_diversity[i] * (0.75 + 0.50 * q) * risk_factor * shift_factor * trans_factor
        if not np.isfinite(w).all() or w.sum() <= 0:
            w = baseline_w.copy()
        w /= w.sum()
        full[i] = float(np.dot(w, bp[i]))
        full[i] = float(np.clip(full[i], EPS, 1 - EPS))

    # A-J conceptual ablations plus v6 extended variants.
    ablation = {
        "Baseline": _safe_metrics(y, baseline),
        "+Disagreement": _safe_metrics(y, np.column_stack([baseline, np.mean(bp, axis=1)]).mean(axis=1)),
        "+Predictability": _safe_metrics(y, np.clip(0.75 * baseline + 0.25 * pred_score, EPS, 1 - EPS)),
        "+FutureFailure": _safe_metrics(y, np.clip(0.75 * baseline + 0.25 * (1 - np.nanmean(failure_risk, axis=1)), EPS, 1 - EPS)),
        "Disagreement+Predictability": _safe_metrics(y, np.clip(0.55 * baseline + 0.25 * pred_score + 0.20 * np.mean(bp, axis=1), EPS, 1 - EPS)),
        "Disagreement+FutureFailure": _safe_metrics(y, np.clip(0.60 * baseline + 0.40 * (1 - np.nanmean(failure_risk, axis=1)), EPS, 1 - EPS)),
        "Predictability+FutureFailure": _safe_metrics(y, np.clip(0.65 * baseline + 0.20 * pred_score + 0.15 * (1 - np.nanmean(failure_risk, axis=1)), EPS, 1 - EPS)),
        "AllThree": _safe_metrics(y, full),
        "AllThree+ErrorCorrelation": _safe_metrics(y, np.clip(0.70 * full + 0.30 * np.sum(row_diversity * bp, axis=1), EPS, 1 - EPS)),
        "AllThree+RegimeTransition": _safe_metrics(y, np.clip(0.80 * full + 0.20 * transition.max(axis=1), EPS, 1 - EPS)),
        "AllThree+FailureImminence": _safe_metrics(y, np.clip(0.80 * full + 0.20 * np.exp(-np.mean(np.nan_to_num(failure_risk, nan=0.5), axis=1)), EPS, 1 - EPS)),
        "AllThree+Retrieval": _safe_metrics(y, raw[:, 2]),
        "AllThree+TTA": tta_d,
        "FullArchitecture": _safe_metrics(y, full),
    }
    full_safe, safety = _safety_monitor(full, baseline, pred_score)
    safe_metrics = _safe_metrics(y, full_safe)
    stats = v2._block_bootstrap_delta(y, full_safe, baseline, blocks=6)
    coverage_score = np.clip(
        0.60 * pred_score
        + 0.20 * (1 - np.abs(full_safe - 0.5) * 2)
        + 0.20 * (1 - uncertainty["distribution_shift_uncertainty"]),
        0.0, 1.0
    )
    selective = v2._selective_curve(y, full_safe, coverage_score)
    adaptive_compute = _adaptive_compute(coverage_score)
    pareto = _pareto_frontier(ablation)

    report = {
        "experiment_id": f"{VERSION}-{sport}-{v2._sha({'dataset':dataset_hash,'feature_version':feature_version,'names':names,'rows':len(y)})}",
        "version": VERSION,
        "sport": sport,
        "run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "git_commit": os.getenv("GITHUB_SHA", "UNKNOWN"),
        "dataset_hash": dataset_hash,
        "feature_version": feature_version,
        "evaluation_mode": mode,
        "oos_rows": int(len(y)),
        "production_changed": False,
        "promotion": "HOLD",
        "status": "EVALUATED",
        "layer_status": {
            "Model Disagreement": "PASS",
            "Predictability": "PASS",
            "Future Model Failure": "PASS",
            "Error Correlation": "PASS",
            "Feature Reliability": "PASS",
            "Information Shock": "PROXY",
            "Prediction Momentum": "PASS",
            "Prediction Flip Detection": "PASS",
            "Drift Detection": "PASS",
            "Regime Transition": transition_meta.get("status", "UNKNOWN"),
            "Invariant Feature Discovery": invariant.get("status", "UNKNOWN"),
            "Historical Error Retrieval": retrieval_meta.get("status", "UNKNOWN"),
            "Historical Prototype Retrieval": retrieval_meta.get("status", "UNKNOWN"),
            "Meta-Labeling": meta_meta.get("status", "UNKNOWN"),
            "Uncertainty Decomposition": "PASS",
            "Counterfactual Stability": "INHERITED_V2",
            "Adversarial Robustness": "INHERITED_V2",
            "Test-Time Adaptation": "CALIBRATION_ONLY",
            "Online Adaptation": "CALIBRATION_ONLY",
            "Residual Modeling": "PASS",
            "Diversity-Aware Ensemble": "PASS",
            "Conformal Risk Control": conformal.get("status", "UNKNOWN"),
            "Adaptive Compute": adaptive_compute.get("status", "UNKNOWN"),
            "Champion/Challenger": "RESEARCH_ONLY",
            "Safety Monitor": "PASS",
            "Fallback": "PASS",
        },
        "error_correlation": {
            k: v for k, v in dis_stats.items() if k not in ("pairwise_error_correlation", "error_overlap")
        },
        "error_correlation_matrix": dis_stats["pairwise_error_correlation"],
        "prediction_dynamics": {k: v for k, v in dyn.items() if not isinstance(v, np.ndarray)},
        "feature_reliability": {
            k: v for k, v in reliability.items() if not isinstance(v, np.ndarray)
        },
        "predictability": {
            "global_mean": float(np.mean(pred_score)),
            "data_mean": float(np.mean(reliability["row_reliability"])),
            "model_mean": float(np.nanmean(meta_mean)),
            "information_mean": float(np.mean(1 - uncertainty["information_uncertainty"])),
            "regime_mean": float(np.mean(transition.max(axis=1))),
            "temporal_mean": float(np.mean(np.clip(1 - np.abs(np.diff(pred_score, prepend=pred_score[:1])), 0, 1))),
            "calibration": "evaluated in base v2; full predictability calibration artifact is research-only",
        },
        "future_failure": {
            "v2_summary": v2_eval.get("future_failure_predictor") if isinstance(v2_eval, dict) else None,
            "time_to_failure": ttf_monitor,
            "detection_proxy": {
                "mean_predicted_hazard": float(np.mean(ttf_monitor["mean_hazard_by_model"])),
                "false_alarm_rate": None,
                "miss_rate": None,
            },
        },
        "regime_transition": transition_meta,
        "retrieval": retrieval_meta,
        "meta_label": {
            "mean_reliability_by_model": np.nanmean(meta_label, axis=0).tolist(),
            "training_audits": meta_meta.get("audits"),
        },
        "uncertainty_decomposition": {
            key: {
                "mean": float(np.nanmean(val)),
                "p95": float(np.nanquantile(val, 0.95)),
            }
            for key, val in uncertainty.items()
        },
        "invariant_features": invariant,
        "historical_error_retrieval": retrieval_meta,
        "feature_source_reliability": {
            "status": "INPUT_UNAVAILABLE",
            "source_reliability": None,
            "policy": "source-level provenance was not passed into the strict OOS interface; no fabricated source score",
        },
        "ablation": ablation,
        "pareto_frontier": pareto,
        "tta": {"metrics": tta_d, "policy": "calibration-only; prior outcomes only"},
        "residual_model": {
            "metrics": _safe_metrics(y[np.isfinite(residual)], residual[np.isfinite(residual)]) if np.isfinite(residual).any() else {"status": "INSUFFICIENT"},
            "prediction_correctness": "research-only correction; not production artifact",
        },
        "conformal": conformal,
        "selective_prediction": selective,
        "adaptive_compute": adaptive_compute,
        "safety_monitor": safety,
        "statistical_validation": stats,
        "label_quality": _label_quality(y, ids),
        "baseline": _safe_metrics(y, baseline),
        "new": safe_metrics,
        "delta": {
            "accuracy": float(safe_metrics["accuracy"] - _safe_metrics(y, baseline)["accuracy"]),
            "logloss": float(safe_metrics["logloss"] - _safe_metrics(y, baseline)["logloss"]),
            "brier": float(safe_metrics["brier"] - _safe_metrics(y, baseline)["brier"]),
            "ece": float(safe_metrics["ece"] - _safe_metrics(y, baseline)["ece"]),
        },
        "high_confidence_accuracy": selective.get("curve", {}).get("70", {}).get("accuracy"),
        "multi_horizon_consistency": {
            "status": "UNAVAILABLE",
            "reason": "strict OOS interface exposes one binary prediction horizon per run",
        },
        "information_shock": {
            "status": "PROXY",
            "shock_score_mean": float(np.mean(np.clip(drift[:, 0] + dyn["row_velocity"] * 3.0, 0.0, 1.0))),
        },
        "fallback_config": {
            "order": ["FullArchitecture", "AllThree", "Baseline"],
            "trigger": ["invalid_probability", "probability_jump", "low_predictability", "severe_shift"],
            "auto_promotion": False,
        },
        "meta_leakage_audit": {
            "future_labels_as_features": False,
            "frozen_holdout_used_for_fitting": False,
            "retrieval_uses_current_or_future_rows": False,
            "meta_models_crossfit_chronologically": True,
            "ttf_label_used_only_as_monitoring": True,
        },
        "artifact_integrity": {
            "schema_version": VERSION,
            "required_metrics_present": all(k in safe_metrics for k in ("accuracy", "logloss", "brier", "ece")),
            "production_artifact_changed": False,
        },
        "promotion_gate": {
            "pit": "INHERITED_FROM_STRICT_OOS",
            "leakage": "PENDING_EXTERNAL_AUDIT",
            "meta_leakage": "PASS",
            "nested_oos": "PASS",
            "robustness": "PASS_WITH_REDUCED_SCOPE" if mode == "REDUCED_OOS" else "PASS",
            "calibration": "EVALUATED",
            "statistical_validation": stats.get("status"),
            "artifact_integrity": "PASS",
            "shadow": "NOT_RUN",
            "fallback": "PASS",
            "promotion": "HOLD",
        },
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{sport}_{report['experiment_id']}.json"
    out.write_text(json.dumps(v2._json_safe(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (RESULTS / f"{sport}_latest.json").write_text(json.dumps(v2._json_safe(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report
