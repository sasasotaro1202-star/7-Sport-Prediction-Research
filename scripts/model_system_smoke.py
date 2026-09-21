from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from src import dynamic_model_router as router
from src import future_predictor
from src import research_cycle_v4 as base


def main():
    rng=np.random.default_rng(42)
    X=rng.normal(size=(320,12))
    y=(X[:,0]-0.6*X[:,1]+0.35*X[:,2]+rng.normal(scale=0.9,size=len(X))>0).astype(int)
    current=X[-8:]+rng.normal(scale=0.05,size=(8,12))
    train=X[:220]

    pool=base.pool()
    required={'logistic','extra_trees','random_forest','hist_gb','hist_gb_shallow','hist_gb_fast','lightgbm','lightgbm_wide'}
    missing=required-set(pool)
    assert not missing, f"model pool missing: {sorted(missing)}"

    ctx=router._context(train,current)
    assert ctx.shape==(len(current),10)
    ref=router.context_reference(train)
    ctx_ref=router._context_from_reference(ref,current)
    assert np.allclose(ctx,ctx_ref,equal_nan=True,atol=1e-10)

    names=['logistic','hist_gb','extra_trees','lightgbm']
    base_models=[]
    bp=[]
    for n in names:
        m=pool[n]
        m.fit(train,y[:len(train)])
        base_models.append(m)
        bp.append(np.clip(m.predict_proba(current)[:,1],1e-6,1-1e-6))
    bp=np.column_stack(bp)

    meta_features=np.column_stack([
        np.tile(bp[:1],(220,1)),
        rng.normal(size=(220,10)),
        rng.uniform(0,0.2,size=(220,1)),
        rng.uniform(0.3,0.9,size=(220,4)),
    ])
    meta_losses=np.clip(rng.normal(loc=0.68,scale=0.08,size=(220,len(names))),0.05,2.0)
    recent_list=router._recent_model_loss(meta_losses.tolist(),len(names))
    recent_array=router._recent_model_loss(meta_losses,len(names))
    assert recent_list.shape==(len(names),) and recent_array.shape==(len(names),) and np.all(np.isfinite(recent_array))
    selector=router._fit_contextual_loss_selector(meta_features,meta_losses)
    assert selector is not None and len(selector['selectors'])==len(names)
    routed=router._route_with_contextual_loss_selector(
        selector,bp,ctx,router._recent_model_loss(meta_losses,len(names))
    )
    assert routed.shape==(len(current),) and np.all(np.isfinite(routed)) and np.all((routed>0)&(routed<1))

    routed2,_=router.predict_with_router(selector,base_models,names,ref,current)
    assert routed2.shape==(len(current),) and np.all(np.isfinite(routed2))
    folds=[]
    for end,te in [(60,100),(100,140),(140,180),(180,220)]:
        preds={n:np.clip(rng.uniform(0.08,0.92,size=te-end),1e-6,1-1e-6) for n in names}
        folds.append({'end':end,'te':te,'preds':preds})
    final_selector=router.fit_final_router_from_folds(X,y,names,folds,220)
    assert final_selector is not None and final_selector.get('kind')=='contextual_loss_v1'
    holdout_pred={n:np.clip(rng.uniform(0.08,0.92,size=len(y)-220),1e-6,1-1e-6) for n in names}
    router_hold=router.evaluate_frozen_holdout_router_from_folds(X,y,names,folds,220,holdout_pred)
    assert router_hold.get('status') in {'EVALUATED','INSUFFICIENT_OOS'}

    p=np.clip(np.linspace(0.1,0.9,120),1e-6,1-1e-6)
    yy=(p>0.55).astype(int)
    sig=LogisticRegression(C=.25,max_iter=1000,random_state=42).fit(np.log(p/(1-p)).reshape(-1,1),yy)
    beta=LogisticRegression(C=.25,max_iter=1000,random_state=42).fit(np.column_stack([np.log(p),np.log(1-p)]),yy)
    iso=IsotonicRegression(out_of_bounds='clip').fit(p,yy)
    for method,cal in [('sigmoid',sig),('beta',beta),('isotonic',iso)]:
        out=future_predictor._apply_calibration(p,cal,method)
        assert out.shape==p.shape and np.all(np.isfinite(out)) and np.all((out>=1e-6)&(out<=1-1e-6))

    weights={'logistic':0.2,'hist_gb':0.3,'extra_trees':0.2,'lightgbm':0.3}
    assert abs(sum(weights.values())-1.0)<1e-12

    print('MODEL_SYSTEM_SMOKE: PASS')
    print({'models':sorted(pool), 'router_context_dim':int(ctx.shape[1]),
           'router_rows':int(len(meta_features)), 'calibration_methods':['sigmoid','beta','isotonic']})
    return 0


if __name__=='__main__':
    raise SystemExit(main())
