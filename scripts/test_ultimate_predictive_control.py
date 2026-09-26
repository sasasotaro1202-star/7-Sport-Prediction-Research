from __future__ import annotations

import numpy as np

from src import ultimate_predictive_control_oos as u


def _folds():
    rng = np.random.default_rng(7)
    n = 180
    y = rng.integers(0, 2, size=n)
    base = np.clip(0.25 + 0.50 * y + rng.normal(0, 0.10, size=n), 0.01, 0.99)
    p1 = np.clip(base, 0.01, 0.99)
    p2 = np.clip(0.90 * base + 0.05, 0.01, 0.99)
    p3 = np.clip(0.80 * base + 0.10, 0.01, 0.99)
    folds=[]
    for end,te in ((60,90),(90,120),(120,150),(150,180)):
        preds={"m1":p1[end:te],"m2":p2[end:te],"m3":p3[end:te]}
        folds.append({"end":end,"te":te,"preds":preds,"event_ids":[str(i) for i in range(end,te)]})
    return y, folds, {"m1":1/3,"m2":1/3,"m3":1/3}


def main():
    y, folds, weights = _folds()
    ids=[str(i) for i in range(60,180)]
    yy=y[60:180]
    # The controller consumes only the chronological OOF rows represented by folds.
    r=u.run_ultimate_research(
        "synthetic",
        folds,
        yy,
        ids,
        ["m1","m2","m3"],
        weights,
        "2026-09-26T00:00:00+00:00",
        "results/research/synthetic_ultimate_intelligence.json",
    )
    assert r["status"]=="EVALUATED"
    assert r["promotion_status"]=="HOLD_RESEARCH_ONLY_NO_AUTO_PROMOTION"
    assert r["disagreement"]["latest"] >= 0.0
    assert 0.0 <= r["predictability"]["latest"] <= 1.0
    assert r["future_model_failure"]["models"]
    assert r["robustness"]["status"]=="EVALUATED"
    # Probability safety / strict JSON invariants.
    s=u._json_safe(r)
    assert all(v is not None for v in [
        s["disagreement"]["latest"],
        s["predictability"]["latest"],
        s["worst_fold_logloss"],
    ])
    print("ULTIMATE_PREDICTIVE_CONTROL: PASS")


if __name__=="__main__":
    main()
