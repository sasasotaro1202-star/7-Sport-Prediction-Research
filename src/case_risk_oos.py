from __future__ import annotations

"""Chronological case-risk / selective prediction research layer.

Predicts the probability that the incumbent ensemble will be wrong. This is
research-only: it never changes the incumbent probability by itself.
"""

from typing import Dict, Sequence
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline


EPS = 1e-6


def _clip(p):
    return np.clip(np.asarray(p, dtype=float), EPS, 1.0 - EPS)


def _safe_auc(y, p):
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    if len(y) < 20 or len(np.unique(y)) < 2:
        return None
    try:
        return float(roc_auc_score(y, p))
    except ValueError:
        return None


def _safe_ap(y, p):
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    if len(y) < 20 or np.sum(y) == 0:
        return None
    try:
        return float(average_precision_score(y, p))
    except ValueError:
        return None


def _features(bp: np.ndarray, ctx: np.ndarray) -> np.ndarray:
    from src.uncertainty_dynamic_router_oos import uncertainty_features
    bp = _clip(bp)
    ctx = np.asarray(ctx, dtype=float)
    if bp.shape[1] >= 2:
        uf = uncertainty_features(bp, ctx)
    else:
        # Single-model incumbents have no inter-model disagreement surface.
        # Preserve a fixed-width feature schema with neutral uncertainty fields.
        mean_p_tmp = np.mean(bp, axis=1)
        uf = np.column_stack([
            mean_p_tmp, np.zeros(len(bp)),
            -(mean_p_tmp*np.log(mean_p_tmp) + (1.0-mean_p_tmp)*np.log(1.0-mean_p_tmp)),
            np.zeros((len(bp), 7)),
        ])
    mean_p = np.mean(bp, axis=1)
    confidence = np.abs(mean_p - 0.5)
    entropy = -(mean_p*np.log(mean_p) + (1.0-mean_p)*np.log(1.0-mean_p))
    return np.column_stack([mean_p, confidence, entropy, bp, uf, ctx])


def _baseline(bp: np.ndarray, names: Sequence[str], weights: Dict[str, float] | None):
    bp = _clip(bp)
    if weights:
        w = np.asarray([float(weights.get(n, 0.0)) for n in names], dtype=float)
        if np.isfinite(w).all() and w.sum() > 0:
            w /= w.sum()
            return np.sum(bp*w[None, :], axis=1)
    return np.mean(bp, axis=1)


def _risk_coverage(y_error, risk, coverages=(0.9, 0.8, 0.7, 0.6, 0.5)):
    y_error = np.asarray(y_error, dtype=int)
    risk = np.asarray(risk, dtype=float)
    out = {}
    order = np.argsort(risk, kind="mergesort")
    n = len(y_error)
    for c in coverages:
        k = max(1, int(round(n*float(c))))
        kept = y_error[order[:k]]
        out[f"{float(c):.2f}"] = {
            "coverage": float(k/n),
            "error_rate": float(np.mean(kept)),
            "accuracy": float(1.0-np.mean(kept)),
            "n": int(k),
        }
    return out


def _aurc(y_error, risk):
    y_error = np.asarray(y_error, dtype=int)
    risk = np.asarray(risk, dtype=float)
    order = np.argsort(risk, kind="mergesort")
    kept = y_error[order]
    cum = np.cumsum(kept) / np.arange(1, len(kept)+1)
    coverage = np.arange(1, len(kept)+1) / len(kept)
    if len(cum) <= 1:
        return float(cum[0])
    # NumPy 2.0 removed np.trapz; retain compatibility with older NumPy.
    integrate = getattr(np, "trapezoid", np.trapz)
    return float(integrate(cum, coverage))


def evaluate_selective_case_risk_oof(
    y: np.ndarray,
    names: Sequence[str],
    folds: Sequence[dict],
    baseline_weights: Dict[str, float] | None = None,
    min_training_rows: int = 180,
):
    """Chronological cross-fitted error-risk estimation.

    For each OOS fold, the risk model only sees labels from strictly earlier
    OOS folds. The frozen holdout is never consumed.
    """
    y = np.asarray(y, dtype=int)
    meta_x = []
    meta_error = []
    pred_risk = []
    pred_error = []
    pred_base_risk = []
    fold_metrics = []

    for fold in folds:
        end = int(fold["end"])
        te = int(fold["te"])
        bp = np.column_stack([_clip(np.asarray(fold["preds"][n])) for n in names])
        ctx = np.asarray(fold.get("context"), dtype=float)
        Xf = _features(bp, ctx)
        base = _baseline(bp, names, baseline_weights)
        yf = y[end:te].astype(int)
        err = (base >= 0.5).astype(int) != yf
        err = err.astype(int)

        risk = None
        if len(meta_x) >= min_training_rows and len(np.unique(meta_error)) >= 2:
            model = Pipeline([
                ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                ("scale", StandardScaler()),
                ("clf", LogisticRegression(
                    C=0.5, class_weight="balanced", max_iter=2000, random_state=2401
                )),
            ])
            try:
                model.fit(np.asarray(meta_x, dtype=float), np.asarray(meta_error, dtype=int))
                risk = np.clip(model.predict_proba(Xf)[:, 1], EPS, 1.0-EPS)
            except (ValueError, FloatingPointError):
                risk = None

        if risk is None:
            risk = np.clip(1.0 - np.abs(base-0.5)*2.0, EPS, 1.0-EPS)

        pred_risk.extend(risk.tolist())
        pred_base_risk.extend((1.0 - np.abs(base-0.5)*2.0).tolist())
        pred_error.extend(err.tolist())
        auc = _safe_auc(err, risk)
        ap = _safe_ap(err, risk)
        base_auc = _safe_auc(err, 1.0-np.abs(base-0.5)*2.0)
        fold_metrics.append({
            "end": end, "te": te, "n": int(len(err)),
            "risk_auc": auc, "risk_ap": ap, "baseline_confidence_auc": base_auc,
            "error_rate": float(np.mean(err)) if len(err) else None,
        })

        meta_x.extend(Xf.tolist())
        meta_error.extend(err.tolist())

    if len(pred_error) < 120 or len(np.unique(pred_error)) < 2:
        return {"status": "INSUFFICIENT_OOS", "oos_rows": len(pred_error)}

    ye = np.asarray(pred_error, dtype=int)
    pr = np.asarray(pred_risk, dtype=float)
    br = np.asarray(pred_base_risk, dtype=float)
    auc = _safe_auc(ye, pr)
    ap = _safe_ap(ye, pr)
    bauc = _safe_auc(ye, br)
    rc = _risk_coverage(ye, pr)
    brc = _risk_coverage(ye, br)
    aurc = _aurc(ye, pr)
    baurc = _aurc(ye, br)

    usable = [m for m in fold_metrics if m.get("risk_auc") is not None]
    return {
        "status": "EVALUATED",
        "oos_rows": int(len(ye)),
        "folds": int(len(fold_metrics)),
        "crossfit_folds_with_trained_risk_model": int(len(usable)),
        "risk_auc": auc,
        "risk_average_precision": ap,
        "baseline_confidence_auc": bauc,
        "auc_improvement": None if auc is None or bauc is None else float(auc-bauc),
        "aurc": aurc,
        "baseline_confidence_aurc": baurc,
        "aurc_improvement": float(baurc-aurc),
        "risk_coverage": rc,
        "baseline_confidence_coverage": brc,
        "fold_metrics": fold_metrics,
        "policy": "research_only; chronological cross-fit error-risk; no holdout fitting; risk score does not alter probability",
    }


def fit_final_case_risk_model(
    y: np.ndarray,
    names: Sequence[str],
    folds: Sequence[dict],
    baseline_weights: Dict[str, float] | None = None,
):
    """Fit final research-only risk model on all pre-holdout OOS rows."""
    y = np.asarray(y, dtype=int)
    xs = []
    ys = []
    for fold in folds:
        end = int(fold["end"])
        te = int(fold["te"])
        bp = np.column_stack([_clip(np.asarray(fold["preds"][n])) for n in names])
        ctx = np.asarray(fold.get("context"), dtype=float)
        base = _baseline(bp, names, baseline_weights)
        err = ((base >= 0.5).astype(int) != y[end:te]).astype(int)
        xs.extend(_features(bp, ctx).tolist())
        ys.extend(err.tolist())
    if len(xs) < 180 or len(np.unique(ys)) < 2:
        return None
    model = Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(
            C=0.5, class_weight="balanced", max_iter=2000, random_state=2401
        )),
    ])
    model.fit(np.asarray(xs, dtype=float), np.asarray(ys, dtype=int))
    return {
        "kind": "selective_case_risk_logistic_v1",
        "model": model,
        "training_rows": int(len(xs)),
        "policy": "pre_holdout_oos_only",
    }


def predict_case_risk(model_bundle, base_probs: np.ndarray, context: np.ndarray):
    if not model_bundle:
        return None
    X = _features(np.asarray(base_probs, dtype=float), np.asarray(context, dtype=float))
    m = model_bundle.get("model")
    if m is None:
        return None
    return np.clip(m.predict_proba(X)[:, 1], EPS, 1.0-EPS)
