#!/usr/bin/env python3
from __future__ import annotations

import numpy as np


def main() -> int:
    import src.dynamic_model_router as router
    import src.future_predictor as future
    import src.research_cycle_strict as strict
    import src.research_cycle_v4 as base

    print("IMPORTS=PASS")
    print("MODEL_POOL", sorted(base.pool().keys()))
    assert router is not None
    assert future is not None
    assert strict is not None
    assert "extra_trees_missing" in base.pool()
    assert "hist_gb_missing" in base.pool()
    assert "lightgbm_missing" in base.pool()
    assert "lightgbm_time_decay_300" in base.pool()
    assert "SymmetricAugment" in base.__dict__

    combat_pool = base.pool(["A__x", "B__x", "D__x", "context"], symmetric=True)
    for required in (
        "extra_trees_missing_symmetric",
        "hist_gb_missing_symmetric",
    ):
        assert required in combat_pool

    fsym = ["A__x", "B__x", "D__x", "context"]
    sm = base.SymmetricAugment(base.pool()["logistic"].b, fsym)
    Xsym = np.array([[0.0, 1.0, 2.0, 3.0], [1.0, 0.0, -2.0, 3.0]])
    ysym = np.array([1, 0])
    mirror = sm._mirror(Xsym)
    assert np.allclose(mirror[0], [1.0, 0.0, -2.0, 3.0])
    sm.fit(Xsym, ysym)
    p_sym = sm.predict_proba(Xsym[:1])
    assert p_sym.shape == (1, 2) and np.isfinite(p_sym).all()

    print("IMPORT_CONTRACT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
