from __future__ import annotations
import sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from src import dynamic_model_router as router
from src import research_cycle_strict as strict


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

    # Multiclass must fail closed for the binary router.
    multi=router.evaluate_router(
        np.zeros((10,2)),np.array([0,1,2,0,1,2,0,1,2,0]),
        ['a','b'],5,2,1,lambda:{},None
    )
    assert multi.get('status')=='UNSUPPORTED_MULTICLASS_RESEARCH_ONLY', multi

    # Probability calibration challenger must not fabricate acceptance on weak data.
    weak=strict._temporal_calibration_candidate(np.full(40,0.5),np.array([0,1]*20))
    assert weak.get('accepted') is False, weak

    # Holdout training contract: no production final fit on rows beyond selection boundary.
    src=(strict.ROOT/'src/research_cycle_strict.py').read_text(encoding='utf-8').replace(' ','')
    assert 'final.fit(X,y)' not in src, 'full-dataset final fit detected'
    print('MODEL PIPELINE VALIDATION: PASS')


if __name__=='__main__':
    main()
