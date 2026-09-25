from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np

from src import research_cycle_v4 as base

ROOT = Path(__file__).resolve().parents[1]
DB_DEFAULT = ROOT / "data/db/sports_v45.sqlite"
REGISTRY_DEFAULT = ROOT / "results/research/ufc_frozen_holdout.json"


def _artifact(path: Path) -> dict:
    obj = joblib.load(path)
    if not isinstance(obj, dict):
        raise RuntimeError(f"invalid_artifact_type:{path}")
    required = ("features", "models", "model_names", "ensemble_weights", "model_version")
    missing = [k for k in required if k not in obj]
    if missing:
        raise RuntimeError(f"artifact_missing:{path}:{missing}")
    features = [str(x) for x in obj["features"]]
    names = [str(x) for x in obj["model_names"]]
    models = list(obj["models"])
    weights = {str(k): float(v) for k, v in (obj.get("ensemble_weights") or {}).items()}
    if not features or not names or len(models) != len(names):
        raise RuntimeError(f"artifact_schema_invalid:{path}")
    if any(name not in weights for name in names):
        raise RuntimeError(f"artifact_weights_missing:{path}:{names}")
    if sum(weights[n] for n in names) <= 0:
        raise RuntimeError(f"artifact_weights_invalid:{path}")
    return obj


def _apply_saved_calibration(raw: np.ndarray, calibrator):
    raw = np.clip(np.asarray(raw, dtype=float), 1e-6, 1 - 1e-6)
    if calibrator is None:
        return raw
    if hasattr(calibrator, "coef_") and hasattr(calibrator, "predict_proba"):
        coef = np.asarray(getattr(calibrator, "coef_"))
        if coef.ndim == 2 and coef.shape[1] == 1:
            z = np.log(raw / (1.0 - raw)).reshape(-1, 1)
            return np.clip(calibrator.predict_proba(z)[:, 1], 1e-6, 1 - 1e-6)
        if coef.ndim == 2 and coef.shape[1] == 2:
            z = np.column_stack([np.log(raw), np.log(1.0 - raw)])
            return np.clip(calibrator.predict_proba(z)[:, 1], 1e-6, 1 - 1e-6)
    if hasattr(calibrator, "predict"):
        return np.clip(np.asarray(calibrator.predict(raw), dtype=float), 1e-6, 1 - 1e-6)
    raise RuntimeError(f"unsupported_calibrator:{type(calibrator).__name__}")


def _predict_fitted(obj: dict, X: np.ndarray, calibrate: bool) -> np.ndarray:
    names = [str(x) for x in obj["model_names"]]
    models = list(obj["models"])
    weights = {str(k): float(v) for k, v in (obj["ensemble_weights"] or {}).items()}
    w = np.asarray([weights[n] for n in names], dtype=float)
    w /= w.sum()
    probs = np.column_stack([
        np.clip(np.asarray(model.predict_proba(X)[:, 1], dtype=float), 1e-6, 1 - 1e-6)
        for model in models
    ])
    raw = np.sum(probs * w[None, :], axis=1)
    return _apply_saved_calibration(raw, obj.get("probability_calibrator")) if calibrate else raw


def _matrix(rows, features):
    available = {str(k) for r in rows for k in (r[3] or {}).keys()}
    missing = [f for f in features if f not in available]
    if missing:
        raise RuntimeError(f"features_missing_from_current_pit_build:{missing[:20]}")
    return np.asarray([[r[3].get(f, np.nan) for f in features] for r in rows], dtype=float)


def _wfo_oos(rows, holdout_ids, incumbent, candidate):
    holdout_set = {str(x) for x in holdout_ids}
    train_rows = [r for r in rows if str(r[0]) not in holdout_set]
    if len(train_rows) < 100:
        raise RuntimeError(f"insufficient_train_rows:{len(train_rows)}")

    sel = len(train_rows)
    start = min(max(60, int(sel * 0.55)), max(60, sel - 20))
    target_folds = min(12, max(6, sel // 500))
    step = max(10, int(np.ceil(max(1, sel - start) / target_folds)))

    specs = {"incumbent": incumbent, "candidate": candidate}
    prepared = {}
    for label, obj in specs.items():
        fs = [str(x) for x in obj["features"]]
        X = _matrix(train_rows, fs)
        y = np.asarray([r[2] for r in train_rows], dtype=int)
        symmetric = True
        prepared[label] = (fs, X, y, symmetric)

    preds = {"incumbent": [], "candidate": []}
    targets = []
    fold_metrics = {"incumbent": [], "candidate": [], "paired_delta": []}
    folds = []

    for end in range(start, sel, step):
        te = min(end + step, sel)
        if len(np.unique(prepared["candidate"][2][:end])) < 2:
            continue
        fold_pred = {}
        for label, obj in specs.items():
            fs, X, y, symmetric = prepared[label]
            pool = base.pool(fs, symmetric=symmetric)
            fold_models = []
            names = [str(x) for x in obj["model_names"]]
            weights = {str(k): float(v) for k, v in (obj["ensemble_weights"] or {}).items()}
            ww = np.asarray([weights[n] for n in names], dtype=float)
            ww /= ww.sum()
            for name in names:
                if name not in pool:
                    raise RuntimeError(f"model_not_in_current_pool:{label}:{name}")
                m = pool[name]
                m.fit(X[:end], y[:end])
                fold_models.append(m)
            bp = np.column_stack([
                np.clip(m.predict_proba(X[end:te])[:, 1], 1e-6, 1 - 1e-6)
                for m in fold_models
            ])
            fold_pred[label] = np.sum(bp * ww[None, :], axis=1)
            preds[label].extend(fold_pred[label].tolist())
        yy = prepared["candidate"][2][end:te]
        if len(yy) >= 20 and len(np.unique(yy)) > 1:
            im = base.metric(yy, np.asarray(fold_pred["incumbent"]))
            cm = base.metric(yy, np.asarray(fold_pred["candidate"]))
            fold_metrics["incumbent"].append(im)
            fold_metrics["candidate"].append(cm)
            fold_metrics["paired_delta"].append(float(cm["logloss"] - im["logloss"]))
            folds.append({"end": end, "te": te, "n": int(te - end)})

    if len(targets) == 0:
        # Targets are reconstructed once from the same fold layout below.
        targets = [prepared["candidate"][2][f["end"]:f["te"]] for f in folds]
    y_oos = np.concatenate(targets) if targets else np.empty(0, dtype=int)
    for label in preds:
        p = np.asarray(preds[label], dtype=float)
        if len(p) != len(y_oos):
            raise RuntimeError(f"oos_alignment_error:{label}:{len(p)}:{len(y_oos)}")

    if len(y_oos) < 60 or len(folds) < 6:
        raise RuntimeError(f"insufficient_auditable_oos:{len(y_oos)}:{len(folds)}")

    def aggregate(label):
        return base.metric(y_oos, np.asarray(preds[label], dtype=float))

    deltas = np.asarray(fold_metrics["paired_delta"], dtype=float)
    block_deltas = []
    if len(deltas) >= 3:
        for idx in np.array_split(np.arange(len(deltas)), 3):
            if len(idx):
                block_deltas.append(float(np.mean(deltas[idx])))

    bootstrap_p05 = float("-inf")
    bootstrap_prob = 0.0
    if len(deltas) >= 6:
        rng = np.random.default_rng(20260925)
        idx = rng.integers(0, len(deltas), size=(2000, len(deltas)))
        imp = -deltas[idx].mean(axis=1)
        bootstrap_p05 = float(np.quantile(imp, 0.05))
        bootstrap_prob = float(np.mean(imp > 0.0))

    return {
        "rows": int(len(y_oos)),
        "folds": int(len(folds)),
        "incumbent": aggregate("incumbent"),
        "candidate": aggregate("candidate"),
        "logloss_improvement": float(aggregate("incumbent")["logloss"] - aggregate("candidate")["logloss"]),
        "brier_improvement": float(aggregate("incumbent")["brier"] - aggregate("candidate")["brier"]),
        "ece_change": float(aggregate("candidate")["ece"] - aggregate("incumbent")["ece"]),
        "fold_logloss_deltas": deltas.tolist(),
        "fold_logloss_delta_std": float(deltas.std(ddof=1)) if len(deltas) > 1 else float("inf"),
        "nonoverlap_block_deltas": block_deltas,
        "nonoverlap_block_improvement_count": int(sum(1 for d in block_deltas if d < 0.0)),
        "bootstrap_p05_improvement": bootstrap_p05,
        "bootstrap_probability_improvement": bootstrap_prob,
        "calibration": "raw_OOS_only; saved final calibrators are score-only on the frozen holdout",
    }


def _holdout(rows, holdout_ids, incumbent, candidate):
    holdout_set = {str(x) for x in holdout_ids}
    hr = [r for r in rows if str(r[0]) in holdout_set]
    if len(hr) < 30:
        raise RuntimeError(f"insufficient_holdout_rows:{len(hr)}")
    y = np.asarray([r[2] for r in hr], dtype=int)
    out = {}
    for label, obj in (("incumbent", incumbent), ("candidate", candidate)):
        X = _matrix(hr, [str(x) for x in obj["features"]])
        out[label] = base.metric(y, _predict_fitted(obj, X, calibrate=True))
    return {
        "rows": int(len(hr)),
        "incumbent": out["incumbent"],
        "candidate": out["candidate"],
        "logloss_improvement": float(out["incumbent"]["logloss"] - out["candidate"]["logloss"]),
        "brier_improvement": float(out["incumbent"]["brier"] - out["candidate"]["brier"]),
        "ece_change": float(out["candidate"]["ece"] - out["incumbent"]["ece"]),
        "note": "single immutable registry; labels are score-only and never used for candidate fitting",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_DEFAULT))
    ap.add_argument("--registry", default=str(REGISTRY_DEFAULT))
    ap.add_argument("--incumbent", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()

    import sqlite3
    conn = sqlite3.connect(a.db)
    try:
        rows, _ = base.build(conn, "ufc")
    finally:
        conn.close()

    reg = json.loads(Path(a.registry).read_text(encoding="utf-8"))
    ids = [str(x) for x in (reg.get("event_ids") or [])]
    if not ids or reg.get("sport") != "ufc":
        raise SystemExit("INVALID_HOLDOUT_REGISTRY")
    current_ids = {str(r[0]) for r in rows}
    missing = [x for x in ids if x not in current_ids]
    if missing:
        raise SystemExit(f"HOLDOUT_REGISTRY_MISSING_EVENTS:{len(missing)}")

    incumbent = _artifact(Path(a.incumbent))
    candidate = _artifact(Path(a.candidate))
    oos = _wfo_oos(rows, ids, incumbent, candidate)
    holdout = _holdout(rows, ids, incumbent, candidate)

    report = {
        "status": "COMPARED",
        "sport": "ufc",
        "registry_hash": str(reg.get("registry_hash")),
        "registry_row_count_at_freeze": reg.get("row_count_at_freeze"),
        "current_strict_pit_rows": len(rows),
        "incumbent_model_version": incumbent.get("model_version"),
        "candidate_model_version": candidate.get("model_version"),
        "oos": oos,
        "frozen_holdout": holdout,
        "production_model_changed": False,
        "adoption_status": "RESEARCH_ONLY_PENDING_GATE",
    }
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
