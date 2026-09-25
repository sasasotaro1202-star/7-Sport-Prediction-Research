from __future__ import annotations

import numpy as np

from src.case_risk_oos import (
    evaluate_selective_case_risk_oof,
    fit_final_case_risk_model,
    predict_case_risk,
)


def main() -> None:
    rng = np.random.default_rng(42)
    y = (rng.random(420) > 0.5).astype(int)
    names = ["a", "b", "c"]

    folds = []
    start = 0
    for i in range(7):
        end = 60 + i * 30
        te = end + 30
        bp = np.clip(
            0.25 + 0.50 * rng.random(te - end)[:, None]
            + 0.08 * rng.normal(size=(te - end, 3)),
            1e-3, 1-1e-3
        )
        # Inject a deterministic hard-case signal in the later folds so the
        # meta-risk pipeline gets non-degenerate error labels.
        ctx = rng.normal(size=(te - end, 33))
        ctx[::7, 5] = np.nan
        ctx[::11, 17] = np.nan
        bp[::13, 1] = np.nan
        ctx[:, 3] = rng.normal(scale=0.5, size=te-end)
        preds = {n: bp[:, j] for j, n in enumerate(names)}
        folds.append({"end": end, "te": te, "preds": preds, "context": ctx})
        start = te

    result = evaluate_selective_case_risk_oof(y, names, folds)
    assert result["status"] == "EVALUATED"
    assert result["oos_rows"] >= 120
    assert np.isfinite(result["aurc"])

    single_names = ["single"]
    single_folds = [dict(f, preds={"single": np.asarray(f["preds"]["a"])}) for f in folds]
    single_result = evaluate_selective_case_risk_oof(y, single_names, single_folds)
    assert single_result["status"] == "EVALUATED"

    bundle = fit_final_case_risk_model(y, names, folds)
    assert bundle is not None
    risk = predict_case_risk(
        bundle,
        np.column_stack([folds[-1]["preds"][n] for n in names]),
        folds[-1]["context"],
    )
    assert risk is not None and np.all(np.isfinite(risk))
    assert np.all((risk > 0.0) & (risk < 1.0))
    print("CASE_RISK_OOS_SMOKE=PASS")


if __name__ == "__main__":
    main()
