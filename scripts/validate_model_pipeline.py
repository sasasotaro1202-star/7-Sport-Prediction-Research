from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from src import dynamic_model_router as router
from src import research_cycle_strict as strict
from src import future_predictor as future


def main():
    # Context must be row-local and finite.
    tr=np.array([[0.,1.],[1.,2.],[2.,3.],[3.,4.]],dtype=float)
    cu=np.array([[3.,4.],[20.,21.]],dtype=float)
    ctx=router._context(tr,cu)
    assert ctx.shape==(2,10), ctx.shape
    assert np.all(np.isfinite(ctx)), "router context contains non-finite values"
    assert not np.allclose(ctx[0],ctx[1]), "router context collapsed to one aggregate"

    # Recent model-loss state must use only supplied historical OOF losses.
    recent=router._recent_model_loss([[0.7,0.5],[0.4,0.8],[0.3,0.6]],2)
    assert recent.shape==(2,)
    assert np.all(np.isfinite(recent)), recent

    # End-to-end contextual router smoke test: fit on synthetic chronological OOF
    # loss data and verify finite situation-specific routing output.
    rng=np.random.default_rng(42)
    meta_features=rng.normal(size=(160,15))
    meta_losses=np.column_stack([
        0.55+0.20*(meta_features[:,0]>0)+rng.normal(0,0.03,160),
        0.60+0.15*(meta_features[:,1]>0)+rng.normal(0,0.03,160),
    ])
    selector=router._fit_contextual_loss_selector(meta_features,meta_losses)
    assert selector is not None and selector.get('kind')=='contextual_loss_v1', selector
    bp=np.clip(rng.uniform(.1,.9,size=(8,2)),1e-6,1-1e-6)
    routed=router._route_with_contextual_loss_selector(
        selector,bp,np.asarray([[0.1]*10,[0.2]*10,[0.3]*10,[0.4]*10,[0.5]*10,[0.6]*10,[0.7]*10,[0.8]*10]),
        router._recent_model_loss(meta_losses.tolist(),2)
    )
    assert routed.shape==(8,) and np.all(np.isfinite(routed)), routed
    assert np.all((routed>0)&(routed<1)), routed

    # Multiclass must fail closed for the binary router.
    multi=router.evaluate_router(
        np.zeros((10,2)),np.array([0,1,2,0,1,2,0,1,2,0]),
        ['a','b'],5,2,1,lambda:{},None
    )
    assert multi.get('status')=='UNSUPPORTED_MULTICLASS_RESEARCH_ONLY', multi

    assert future._after_now("2999-01-01T00:00:00+00:00", datetime.now(timezone.utc)) is True
    assert future._after_now("2000-01-01T00:00:00+00:00", datetime.now(timezone.utc)) is False
    assert np.allclose(future._apply_calibration(np.array([0.25,0.75]),None,'none'),np.array([0.25,0.75]))
    
    # Probability calibration challenger must not fabricate acceptance on weak data.
    weak=strict._temporal_calibration_candidate(np.full(40,0.5),np.array([0,1]*20))
    assert weak.get('accepted') is False, weak

    # Holdout training contract: no production final fit on rows beyond selection boundary.
    src=(strict.ROOT/'src/research_cycle_strict.py').read_text(encoding='utf-8').replace(' ','')
    assert 'final.fit(X,y)' not in src, 'full-dataset final fit detected'
    print('MODEL PIPELINE VALIDATION: PASS')


if __name__=='__main__':
    main()
