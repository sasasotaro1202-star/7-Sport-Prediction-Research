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
from sklearn.ensemble import HistGradientBoostingRegressor
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
    # Recent-vs-long-history regime signals: all are computed from data available
    # before the current fold/row and therefore remain PIT-safe.
    recent_n = min(120, len(tr))
    recent = tr[-recent_n:] if recent_n else tr
    recent_med = np.nanmedian(recent, axis=0) if recent.size else tr_med
    recent_med = np.where(np.isfinite(recent_med), recent_med, tr_med)
    regime_z = np.abs(recent_med - tr_med) / tr_scale
    regime_shift = float(np.nanmedian(regime_z)) if regime_z.size else 0.0
    recent_std = np.nanmedian(np.nanstd(recent, axis=0)) if recent.size else train_feature_std
    recent_std = float(recent_std) if np.isfinite(recent_std) else train_feature_std
    recent_z = np.abs(np.nan_to_num(cu, nan=recent_med) - recent_med) / tr_scale
    recent_z = np.where(np.isfinite(recent_z), recent_z, 0.0)
    row_recent_shift = np.nanmedian(recent_z, axis=1) if recent_z.size else np.zeros(len(cu))
    row_recent_shift = np.where(np.isfinite(row_recent_shift), row_recent_shift, 0.0)
    train_size = np.log1p(len(tr))
    return np.column_stack([
        np.full(len(cu), train_size, dtype=float),
        np.full(len(cu), train_miss, dtype=float),
        row_miss.astype(float),
        row_shift.astype(float),
        row_abs_z.astype(float),
        row_dispersion.astype(float),
        np.full(len(cu), train_feature_std, dtype=float),
        np.full(len(cu), regime_shift, dtype=float),
        row_recent_shift.astype(float),
        np.full(len(cu), recent_std, dtype=float),
    ])



def context_reference(train_x: np.ndarray) -> Dict:
    """Compact PIT-safe reference sufficient to reproduce _context exactly."""
    tr=np.asarray(train_x,dtype=float)
    tr_med=np.nanmedian(tr,axis=0) if tr.size else np.zeros(tr.shape[1])
    tr_med=np.where(np.isfinite(tr_med),tr_med,0.0)
    tr_scale=np.nanmedian(np.abs(tr-tr_med),axis=0) if tr.size else np.ones(tr.shape[1])
    tr_scale=np.where(np.isfinite(tr_scale)&(tr_scale>1e-9),tr_scale,1.0)
    recent_n=min(120,len(tr))
    recent=tr[-recent_n:] if recent_n else tr
    recent_med=np.nanmedian(recent,axis=0) if recent.size else tr_med
    recent_med=np.where(np.isfinite(recent_med),recent_med,tr_med)
    regime_z=np.abs(recent_med-tr_med)/tr_scale
    regime_shift=float(np.nanmedian(regime_z)) if regime_z.size else 0.0
    recent_std=float(np.nanmedian(np.nanstd(recent,axis=0))) if recent.size else float(np.nanmedian(np.nanstd(tr,axis=0))) if tr.size else 0.0
    if not np.isfinite(recent_std): recent_std=0.0
    train_feature_std=float(np.nanmedian(np.nanstd(tr,axis=0))) if tr.size else 0.0
    if not np.isfinite(train_feature_std): train_feature_std=0.0
    return {
        'n':int(len(tr)),
        'train_miss':float(np.isnan(tr).mean()) if tr.size else 1.0,
        'tr_med':tr_med.tolist(),
        'tr_scale':tr_scale.tolist(),
        'recent_med':recent_med.tolist(),
        'regime_shift':regime_shift,
        'recent_std':recent_std,
        'train_feature_std':train_feature_std,
    }


def _context_from_reference(reference: Dict, current_x: np.ndarray) -> np.ndarray:
    cu=np.asarray(current_x,dtype=float)
    if cu.ndim==1: cu=cu.reshape(1,-1)
    tr_med=np.asarray(reference.get('tr_med') or np.zeros(cu.shape[1]),dtype=float)
    tr_scale=np.asarray(reference.get('tr_scale') or np.ones(cu.shape[1]),dtype=float)
    recent_med=np.asarray(reference.get('recent_med') or tr_med,dtype=float)
    if len(tr_med)!=cu.shape[1] or len(tr_scale)!=cu.shape[1] or len(recent_med)!=cu.shape[1]:
        return _context(np.asarray(reference.get('fallback_train_x') or [],dtype=float),cu)
    tr_scale=np.where(np.isfinite(tr_scale)&(tr_scale>1e-9),tr_scale,1.0)
    row_miss=np.isnan(cu).mean(axis=1) if cu.size else np.ones(len(cu))
    z=np.abs(np.nan_to_num(cu,nan=tr_med)-tr_med)/tr_scale
    z=np.where(np.isfinite(z),z,0.0)
    row_shift=np.nanmedian(z,axis=1) if z.size else np.zeros(len(cu))
    row_shift=np.where(np.isfinite(row_shift),row_shift,0.0)
    row_abs_z=np.nanmean(z,axis=1) if z.size else np.zeros(len(cu))
    row_abs_z=np.where(np.isfinite(row_abs_z),row_abs_z,0.0)
    row_dispersion=np.nanstd(np.nan_to_num(cu,nan=tr_med),axis=1) if cu.size else np.zeros(len(cu))
    row_dispersion=np.where(np.isfinite(row_dispersion),row_dispersion,0.0)
    recent_z=np.abs(np.nan_to_num(cu,nan=recent_med)-recent_med)/tr_scale
    recent_z=np.where(np.isfinite(recent_z),recent_z,0.0)
    row_recent_shift=np.nanmedian(recent_z,axis=1) if recent_z.size else np.zeros(len(cu))
    row_recent_shift=np.where(np.isfinite(row_recent_shift),row_recent_shift,0.0)
    n=max(0,int(reference.get('n',0)))
    return np.column_stack([
        np.full(len(cu),np.log1p(n),dtype=float),
        np.full(len(cu),float(reference.get('train_miss',1.0)),dtype=float),
        row_miss.astype(float),row_shift.astype(float),row_abs_z.astype(float),
        row_dispersion.astype(float),
        np.full(len(cu),float(reference.get('train_feature_std',0.0)),dtype=float),
        np.full(len(cu),float(reference.get('regime_shift',0.0)),dtype=float),
        row_recent_shift.astype(float),
        np.full(len(cu),float(reference.get('recent_std',0.0)),dtype=float),
    ])

def _recent_model_loss(meta_losses: Sequence[Sequence[float]], n_models: int) -> np.ndarray:
    """Recent OOF log-loss state using only rows observed before the current fold."""
    if meta_losses is None or len(meta_losses) == 0:
        return np.full(n_models, np.log(2.0), dtype=float)
    arr=np.asarray(meta_losses[-180:],dtype=float)
    if arr.ndim!=2 or arr.shape[1]!=n_models:
        return np.full(n_models, np.log(2.0), dtype=float)
    w=np.exp(np.linspace(-1.0,0.0,len(arr)))
    out=np.average(arr,axis=0,weights=w)
    return np.where(np.isfinite(out),out,np.log(2.0))


def _fit_contextual_loss_selector(meta_features: np.ndarray, meta_losses: np.ndarray):
    """Fit one PIT-safe loss forecaster per base model using only prior OOF rows."""
    X = np.asarray(meta_features, dtype=float)
    L = np.asarray(meta_losses, dtype=float)
    if X.ndim != 2 or L.ndim != 2 or len(X) < 120 or len(X) != len(L):
        return None
    selectors = []
    for j in range(L.shape[1]):
        model = HistGradientBoostingRegressor(
            max_iter=120,
            learning_rate=0.04,
            max_leaf_nodes=7,
            min_samples_leaf=20,
            l2_regularization=2.0,
            random_state=42 + j,
        )
        model.fit(X, L[:, j])
        selectors.append(model)
    loss_spread = np.std(L, axis=1)
    finite_spread = loss_spread[np.isfinite(loss_spread) & (loss_spread > 1e-9)]
    spread_scale = float(np.quantile(finite_spread, 0.75)) if len(finite_spread) else 0.05
    spread_scale = max(spread_scale, 1e-3)
    return {
        "kind": "contextual_loss_v1",
        "selectors": selectors,
        "loss_spread_scale": spread_scale,
    }


def _route_with_contextual_loss_selector(
    selector,
    bp: np.ndarray,
    ctx: np.ndarray,
    history_loss=None,
    baseline_weights: Dict[str, float] | None = None,
):
    """Route conservatively toward the exact incumbent ensemble used by production/evaluation.

    Legacy router artifacts without persisted weights fall back to equal weighting.
    """
    if not isinstance(selector, dict) or selector.get("kind") != "contextual_loss_v1":
        return None
    selectors = selector.get("selectors") or []
    if not selectors:
        return None
    hl = np.asarray(history_loss if history_loss is not None else selector.get('history_loss'), dtype=float)
    if hl.ndim != 1 or len(hl) != bp.shape[1]:
        hl = np.full(bp.shape[1], np.log(2.0), dtype=float)
    features = np.column_stack([bp, ctx, np.std(bp, axis=1), np.repeat(hl[None, :], len(bp), axis=0)])
    predicted = np.column_stack([m.predict(features) for m in selectors])
    predicted = np.where(np.isfinite(predicted), predicted, np.nanmedian(predicted, axis=0))
    ref_weights = baseline_weights if baseline_weights is not None else selector.get("baseline_weights")
    baseline = np.mean(bp, axis=1)
    if isinstance(ref_weights, dict):
        try:
            model_names = list(selector.get("model_names") or [])
            w = np.asarray([float(ref_weights.get(name, 0.0)) for name in model_names], dtype=float)
            if len(w) != bp.shape[1] or not np.isfinite(w).all() or w.sum() <= 0:
                raise ValueError("invalid persisted router baseline weights")
            w = w / w.sum()
            baseline = np.sum(bp * w[None, :], axis=1)
        except Exception:
            baseline = np.mean(bp, axis=1)
    # Lower predicted log-loss => larger weight. Temperature prevents brittle winner-take-all routing.
    centered = predicted - np.min(predicted, axis=1, keepdims=True)
    weights = np.exp(-centered / 0.15)
    weights /= np.maximum(weights.sum(axis=1, keepdims=True), 1e-12)
    # Conservative shrinkage toward equal weighting reduces regime overreaction.
    weights = 0.75 * weights + 0.25 / bp.shape[1]
    routed = np.sum(bp * weights, axis=1)

    # Do not route aggressively when the selector itself sees little separation
    # between model losses. The scale is learned only from pre-holdout OOF loss
    # history, so this remains PIT-safe and automatically becomes stronger when
    # the models are meaningfully differentiated.
    spread_scale = float(selector.get("loss_spread_scale", 0.0) or 0.0)
    if np.isfinite(spread_scale) and spread_scale > 1e-9:
        pred_spread = np.max(predicted, axis=1) - np.min(predicted, axis=1)
        confidence = pred_spread / np.maximum(pred_spread + spread_scale, 1e-9)
        route_strength = 0.75 * np.clip(confidence, 0.0, 1.0)
        routed = baseline + route_strength * (routed - baseline)
    else:
        routed = 0.75 * routed + 0.25 * baseline
    return np.clip(routed, 1e-6, 1 - 1e-6)



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


def evaluate_router_from_folds(
    X: np.ndarray,
    y: np.ndarray,
    names: Sequence[str],
    folds: Sequence[Dict],
    sel: int,
    metric=None,
    baseline_weights: Dict[str, float] | None = None,
) -> Dict:
    """Evaluate the contextual router against the exact selected baseline ensemble."""
    X=np.asarray(X,dtype=float); y=np.asarray(y)
    meta_X=[]; meta_losses=[]; static_pred=[]; router_pred=[]; targets=[]; fold_deltas=[]
    used_folds=0
    for fold in folds:
        end=int(fold['end']); te=int(fold['te'])
        bp=np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in names])
        ctx=_context(X[:end],X[end:te])
        history_loss=_recent_model_loss(meta_losses,len(names))
        features=np.column_stack([bp,ctx,np.std(bp,axis=1),np.repeat(history_loss[None,:],len(bp),axis=0)])
        selector=_fit_contextual_loss_selector(
            np.asarray(meta_X,dtype=float) if meta_X else np.empty((0,features.shape[1])),
            np.asarray(meta_losses,dtype=float) if meta_losses else np.empty((0,len(names)))
        )
        if baseline_weights:
            w=np.asarray([float(baseline_weights.get(n,0.0)) for n in names],dtype=float)
            if np.isfinite(w).all() and w.sum()>0:
                w=w/w.sum()
                static=np.sum(bp*w[None,:],axis=1)
            else:
                static=np.mean(bp,axis=1)
        else:
            static=np.mean(bp,axis=1)
        routed=_route_with_contextual_loss_selector(selector,bp,ctx,history_loss,baseline_weights)
        if routed is None:
            routed=static.copy()
        fold_deltas.append(float(_metric(y[end:te],routed)['logloss']-_metric(y[end:te],static)['logloss']))
        static_pred.extend(static.tolist());router_pred.extend(routed.tolist());targets.extend(y[end:te].tolist())
        yt=y[end:te].astype(float)
        losses=-(yt[:,None]*np.log(bp)+(1.0-yt[:,None])*np.log(1.0-bp))
        meta_X.extend(features.tolist());meta_losses.extend(losses.tolist());used_folds+=1
    if len(meta_losses)<120:
        return {'status':'INSUFFICIENT_OOS','reason':'insufficient_router_training_oof','oos_rows':len(meta_losses)}
    static_m=_metric(np.asarray(targets),static_pred);router_m=_metric(np.asarray(targets),router_pred)
    fold_deltas_arr=np.asarray(fold_deltas,dtype=float)
    block_deltas=[]
    if len(fold_deltas_arr)>=3:
        for ids in np.array_split(np.arange(len(fold_deltas_arr)),3):
            vals=fold_deltas_arr[ids]
            if len(vals): block_deltas.append(float(np.mean(vals)))
    bootstrap_prob=0.0; bootstrap_p05=float('-inf')
    if len(fold_deltas_arr)>=6 and np.isfinite(fold_deltas_arr).all():
        rng=np.random.default_rng(20260923)
        idx=rng.integers(0,len(fold_deltas_arr),size=(1000,len(fold_deltas_arr)))
        boot=fold_deltas_arr[idx].mean(axis=1)
        improvement=-boot
        bootstrap_prob=float(np.mean(improvement>0.0))
        bootstrap_p05=float(np.quantile(improvement,0.05))
    return {
        'status':'EVALUATED','folds':used_folds,'oos_rows':len(meta_losses),
        'fixed_ensemble':static_m,'dynamic_router':router_m,
        'logloss_improvement':static_m['logloss']-router_m['logloss'],
        'brier_improvement':static_m['brier']-router_m['brier'],
        'ece_change':router_m['ece']-static_m['ece'],
        'fold_logloss_deltas':fold_deltas_arr.tolist(),
        'nonoverlap_block_deltas':block_deltas,
        'bootstrap_p05_improvement':bootstrap_p05,
        'bootstrap_prob_improvement':bootstrap_prob,
        'policy':'challenger_only; reused chronological OOF base predictions; frozen holdout untouched'
    }

def evaluate_frozen_holdout_router_from_folds(
    X: np.ndarray,
    y: np.ndarray,
    names: Sequence[str],
    folds: Sequence[Dict],
    sel: int,
    holdout_pred: Dict[str, np.ndarray],
    holdout_X: np.ndarray | None = None,
    holdout_y: np.ndarray | None = None,
    baseline_weights: Dict[str, float] | None = None,
) -> Dict:
    """Evaluate contextual router on frozen holdout using precomputed pre-holdout OOF base predictions."""
    X=np.asarray(X,dtype=float); y=np.asarray(y)
    hX=None if holdout_X is None else np.asarray(holdout_X,dtype=float)
    hy=None if holdout_y is None else np.asarray(holdout_y)
    lengths={n:len(np.asarray(holdout_pred.get(n,[]))) for n in names}
    expected=max(lengths.values()) if lengths else 0
    if expected<1 or any(v!=expected for v in lengths.values()):
        return {'status':'INSUFFICIENT_OOS','reason':'holdout_prediction_shape_mismatch','expected_rows':expected,
                'received_rows':lengths}
    if hX is None or hX.ndim!=2 or len(hX)!=expected:
        return {'status':'INSUFFICIENT_OOS','reason':'holdout_feature_shape_mismatch','expected_rows':expected,
                'received_feature_rows':0 if hX is None else len(hX)}
    if hy is None or len(hy)!=expected:
        return {'status':'INSUFFICIENT_OOS','reason':'holdout_target_shape_mismatch','expected_rows':expected,
                'received_target_rows':0 if hy is None else len(hy)}
    meta_X=[]; meta_losses=[]
    for fold in folds:
        end=int(fold['end']); te=int(fold['te'])
        bp=np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in names])
        ctx=_context(X[:end],X[end:te])
        history_loss=_recent_model_loss(meta_losses,len(names))
        features=np.column_stack([bp,ctx,np.std(bp,axis=1),np.repeat(history_loss[None,:],len(bp),axis=0)])
        yt=y[end:te].astype(float)
        losses=-(yt[:,None]*np.log(bp)+(1.0-yt[:,None])*np.log(1.0-bp))
        meta_X.extend(features.tolist());meta_losses.extend(losses.tolist())
    selector=_fit_contextual_loss_selector(np.asarray(meta_X,dtype=float),np.asarray(meta_losses,dtype=float))
    if selector is None:
        return {'status':'INSUFFICIENT_OOS','reason':'insufficient_router_training_oof','oos_rows':len(meta_losses)}
    bp=np.column_stack([np.asarray(holdout_pred[n],dtype=float) for n in names])
    if baseline_weights:
        w=np.asarray([float(baseline_weights.get(n,0.0)) for n in names],dtype=float)
        if np.isfinite(w).all() and w.sum()>0:
            w=w/w.sum()
            static=np.sum(bp*w[None,:],axis=1)
        else:
            static=np.mean(bp,axis=1)
    else:
        static=np.mean(bp,axis=1)
    ctx=_context(X,hX)
    routed=_route_with_contextual_loss_selector(
        selector,bp,ctx,_recent_model_loss(meta_losses,len(names)),baseline_weights
    )
    if routed is None:
        return {'status':'INSUFFICIENT_OOS','reason':'contextual_router_fit_failed','oos_rows':len(meta_losses)}
    target=hy.astype(int)
    static_m=_metric(target,static);routed_m=_metric(target,routed)
    return {'status':'EVALUATED','oos_training_rows':len(meta_losses),'holdout_rows':len(target),'fixed_ensemble':static_m,'dynamic_router':routed_m,'logloss_improvement':static_m['logloss']-routed_m['logloss'],'brier_improvement':static_m['brier']-routed_m['brier'],'ece_change':routed_m['ece']-static_m['ece'],'policy':'router_fit_pre_holdout_only; reused chronological OOF base predictions; frozen_holdout_labels_used_only_for_scoring'}

def evaluate_router(
    X: np.ndarray,
    y: np.ndarray,
    names: Sequence[str],
    sel: int,
    start: int,
    step: int,
    pool_factory,
    metric=None,
) -> Dict:
    """Nested chronological OOS comparison with a contextual loss router."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y)
    if not _require_binary_target(y):
        return {"status": "UNSUPPORTED_MULTICLASS_RESEARCH_ONLY", "reason": "router_is_binary_only"}
    if sel <= start + step or len(names) < 2:
        return {"status": "INSUFFICIENT_OOS", "reason": "too_few_chronological_folds"}

    meta_X = []
    meta_losses = []
    static_pred = []
    router_pred = []
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
        history_loss=_recent_model_loss(meta_losses,len(names))
        features = np.column_stack([bp, ctx, np.std(bp, axis=1), np.repeat(history_loss[None,:], len(bp), axis=0)])

        selector = _fit_contextual_loss_selector(
            np.asarray(meta_X, dtype=float) if meta_X else np.empty((0, features.shape[1])),
            np.asarray(meta_losses, dtype=float) if meta_losses else np.empty((0, len(names))),
        )
        routed = _route_with_contextual_loss_selector(selector, bp, ctx, history_loss)
        if routed is None:
            routed = static.copy()

        static_pred.extend(static.tolist())
        router_pred.extend(routed.tolist())

        yt = y[end:te].astype(float)
        fold_losses = -(
            yt[:, None] * np.log(bp)
            + (1.0 - yt[:, None]) * np.log(1.0 - bp)
        )
        meta_X.extend(features.tolist())
        meta_losses.extend(fold_losses.tolist())
        used_folds += 1

    if len(meta_losses) < 120:
        return {
            "status": "INSUFFICIENT_OOS",
            "reason": "insufficient_router_training_oof",
            "oos_rows": len(meta_losses),
        }

    static_m = _metric(y[start:sel], static_pred)
    router_m = _metric(y[start:sel], router_pred)
    return {
        "status": "EVALUATED",
        "folds": used_folds,
        "oos_rows": len(meta_losses),
        "fixed_ensemble": static_m,
        "dynamic_router": router_m,
        "logloss_improvement": static_m["logloss"] - router_m["logloss"],
        "brier_improvement": static_m["brier"] - router_m["brier"],
        "ece_change": router_m["ece"] - static_m["ece"],
        "policy": "challenger_only; chronological OOF; contextual per-model loss forecasting; frozen holdout untouched",
    }

def evaluate_frozen_holdout_router(
    X: np.ndarray,
    y: np.ndarray,
    names: Sequence[str],
    sel: int,
    start: int,
    step: int,
    pool_factory,
    metric=None,
) -> Dict:
    """Evaluate a contextual loss router fit only on pre-holdout OOF rows."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y)
    if not _require_binary_target(y):
        return {"status": "UNSUPPORTED_MULTICLASS_RESEARCH_ONLY", "reason": "router_is_binary_only"}
    if sel <= start or sel >= len(y) or len(names) < 2:
        return {"status": "INSUFFICIENT_HOLDOUT", "reason": "invalid_frozen_holdout_split"}

    meta_X = []
    meta_losses = []
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
        history_loss=_recent_model_loss(meta_losses,len(names))
        features = np.column_stack([bp, ctx, np.std(bp, axis=1), np.repeat(history_loss[None,:], len(bp), axis=0)])
        yt = y[end:te].astype(float)
        fold_losses = -(
            yt[:, None] * np.log(bp)
            + (1.0 - yt[:, None]) * np.log(1.0 - bp)
        )
        meta_X.extend(features.tolist())
        meta_losses.extend(fold_losses.tolist())

    selector = _fit_contextual_loss_selector(np.asarray(meta_X, dtype=float), np.asarray(meta_losses, dtype=float))
    if selector is None:
        return {"status": "INSUFFICIENT_OOS", "reason": "insufficient_router_training_oof", "oos_rows": len(meta_losses)}

    bp = []
    for name in names:
        model = pool_factory()[name]
        model.fit(X[:sel], y[:sel])
        bp.append(np.clip(model.predict_proba(X[sel:])[:, 1], 1e-6, 1 - 1e-6))
    bp = np.column_stack(bp)
    static = bp.mean(axis=1)
    ctx = _context(X[:sel], X[sel:])
    routed = _route_with_contextual_loss_selector(selector, bp, ctx, _recent_model_loss(meta_losses,len(names)))
    if routed is None:
        return {"status": "INSUFFICIENT_OOS", "reason": "contextual_router_fit_failed", "oos_rows": len(meta_losses)}

    target = y[sel:]
    static_m = _metric(target, static)
    routed_m = _metric(target, routed)
    return {
        "status": "EVALUATED",
        "oos_training_rows": len(meta_losses),
        "holdout_rows": len(target),
        "fixed_ensemble": static_m,
        "dynamic_router": routed_m,
        "logloss_improvement": static_m["logloss"] - routed_m["logloss"],
        "brier_improvement": static_m["brier"] - routed_m["brier"],
        "ece_change": routed_m["ece"] - static_m["ece"],
        "policy": "router_fit_pre_holdout_only; per-model OOF loss targets; frozen_holdout_labels_used_only_for_scoring",
    }

def fit_final_router(X, y, names, sel, start, step, pool_factory):
    """Fit the final contextual loss router from pre-holdout chronological OOF."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y)
    if not _require_binary_target(y):
        return None
    meta_X = []
    meta_losses = []
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
        history_loss=_recent_model_loss(meta_losses,len(names))
        features = np.column_stack([bp, ctx, np.std(bp, axis=1), np.repeat(history_loss[None,:], len(bp), axis=0)])
        yt = y[end:te].astype(float)
        fold_losses = -(
            yt[:, None] * np.log(bp)
            + (1.0 - yt[:, None]) * np.log(1.0 - bp)
        )
        meta_X.extend(features.tolist())
        meta_losses.extend(fold_losses.tolist())
    selector=_fit_contextual_loss_selector(
        np.asarray(meta_X, dtype=float),
        np.asarray(meta_losses, dtype=float),
    )
    if selector is not None:
        selector['history_loss']=_recent_model_loss(meta_losses,len(names))
    return selector

def fit_final_router_from_folds(
    X: np.ndarray,
    y: np.ndarray,
    names: Sequence[str],
    folds: Sequence[Dict],
    sel: int,
    baseline_weights: Dict[str, float] | None = None,
) -> Dict | None:
    """Fit the final contextual loss router from already-computed chronological OOF folds."""
    X=np.asarray(X,dtype=float); y=np.asarray(y)
    meta_X=[]; meta_losses=[]
    for fold in folds:
        end=int(fold['end']); te=int(fold['te'])
        bp=np.column_stack([np.asarray(fold['preds'][n],dtype=float) for n in names])
        ctx=_context(X[:end],X[end:te])
        history_loss=_recent_model_loss(meta_losses,len(names))
        features=np.column_stack([bp,ctx,np.std(bp,axis=1),np.repeat(history_loss[None,:],len(bp),axis=0)])
        yt=y[end:te].astype(float)
        losses=-(yt[:,None]*np.log(bp)+(1.0-yt[:,None])*np.log(1.0-bp))
        meta_X.extend(features.tolist()); meta_losses.extend(losses.tolist())
    selector=_fit_contextual_loss_selector(np.asarray(meta_X,dtype=float),np.asarray(meta_losses,dtype=float))
    if selector is not None:
        selector['history_loss']=_recent_model_loss(meta_losses,len(names))
        selector['model_names']=list(names)
        if isinstance(baseline_weights, dict):
            selector['baseline_weights']={str(k):float(v) for k,v in baseline_weights.items()}
    return selector

def predict_with_router(
    router,
    base_models,
    names,
    train_x,
    current_x,
    baseline_weights: Dict[str, float] | None = None,
):
    bp = []
    for name, model in zip(names, base_models):
        proba = np.asarray(model.predict_proba(current_x))
        if proba.ndim != 2 or proba.shape[1] != 2:
            static = np.full(len(current_x), 0.5, dtype=float)
            return static, {"fallback": True, "reason": "multiclass_base_model_unsupported"}
        bp.append(np.clip(proba[:, 1], 1e-6, 1 - 1e-6))
    bp = np.column_stack(bp)
    static = bp.mean(axis=1)
    if isinstance(baseline_weights, dict):
        try:
            w=np.asarray([float(baseline_weights.get(n,0.0)) for n in names],dtype=float)
            if len(w)==bp.shape[1] and np.isfinite(w).all() and w.sum()>0:
                w=w/w.sum()
                static=np.sum(bp*w[None,:],axis=1)
        except Exception:
            pass
    if router is None:
        return static, {"fallback": True, "reason": "router_unavailable"}
    ctx = _context_from_reference(train_x, current_x) if isinstance(train_x,dict) else _context(train_x, current_x)
    routed = _route_with_contextual_loss_selector(router, bp, ctx)
    if routed is None:
        return static, {"fallback": True, "reason": "contextual_router_unavailable"}
    return routed, {"fallback": False, "router_kind": "contextual_loss_v1", "shrinkage": 0.25}


__all__ = ["DynamicModelRouter", "context_reference", "evaluate_router", "evaluate_router_from_folds", "evaluate_frozen_holdout_router_from_folds", "fit_final_router", "predict_with_router"]
