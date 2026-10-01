from __future__ import annotations

"""Research-only calibration of the predictability proxy.

The calibrator estimates P(prediction-correct | raw predictability) from strictly
prior, outcome-matured OOS observations. The calibrator is frozen before the
locked suffix and never updated with locked outcomes.
"""

from datetime import datetime
from typing import Any, Sequence

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

EPS = 1e-6


def _ts(values: Sequence[Any], name: str) -> list[datetime]:
    out=[]
    for v in values:
        dt=v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z","+00:00"))
        if dt.tzinfo is None:
            raise ValueError(f"{name} must be timezone-aware")
        out.append(dt)
    if not out:
        raise ValueError(f"{name} must be non-empty")
    if any(out[i] < out[i-1] for i in range(1,len(out))):
        raise ValueError(f"{name} must be monotonically non-decreasing")
    return out


def _validate(raw, correctness, prediction_times, outcome_confirmed_at):
    x=np.asarray(raw,float); y=np.asarray(correctness,int)
    pt=_ts(prediction_times,"prediction_times")
    mt=_ts(outcome_confirmed_at,"outcome_confirmed_at")
    if x.ndim!=1 or y.ndim!=1 or len(x)!=len(y) or len(x)!=len(pt) or len(x)!=len(mt):
        raise ValueError("predictability calibration inputs must align")
    if not np.isfinite(x).all():
        raise ValueError("raw predictability must be finite")
    if np.any((x < 0.0) | (x > 1.0)):
        raise ValueError("raw predictability must be in [0,1]")
    if np.any((y != 0) & (y != 1)):
        raise ValueError("correctness labels must be binary")
    if any(m < p for p,m in zip(pt,mt)):
        raise ValueError("outcome_confirmed_at cannot precede prediction_time")
    return x,y,pt,mt


def _fit(x: np.ndarray, y: np.ndarray):
    if len(y) < 120 or len(np.unique(y)) < 2:
        prior=float(np.clip(np.mean(y) if len(y) else 0.5,0.01,0.99))
        return ("PRIOR_MEAN", prior, None)
    model=Pipeline([
        ("scale",StandardScaler()),
        ("logistic",LogisticRegression(C=0.50,max_iter=2000,random_state=13013)),
    ])
    model.fit(x.reshape(-1,1),y)
    return ("FITTED_PRIOR_ONLY_LOGISTIC",None,model)


def chronological_predictability_calibration(
    raw_predictability: Sequence[float],
    correctness: Sequence[int],
    prediction_times: Sequence[Any],
    outcome_confirmed_at: Sequence[Any],
    *,
    locked_start: int,
    min_history: int = 120,
    max_history: int | None = 600,
) -> dict[str,Any]:
    """Calibrate chronologically and freeze the calibrator before locked_start."""
    x,y,pt,mt=_validate(raw_predictability,correctness,prediction_times,outcome_confirmed_at)
    locked_start=int(locked_start)
    if not 1 <= locked_start < len(x):
        raise ValueError("locked_start must split development and locked rows")
    if min_history < 1:
        raise ValueError("min_history must be >= 1")
    if max_history is not None and int(max_history) < min_history:
        raise ValueError("max_history must be >= min_history")

    calibrated=np.full(len(x),np.nan,float)
    status=[]; training_rows=[]
    frozen_fit=None

    for i in range(len(x)):
        if i >= locked_start and frozen_fit is not None:
            kind,prior,model=frozen_fit
        else:
            eligible=[j for j in range(min(i,locked_start)) if pt[j] < pt[i] and mt[j] <= pt[i]]
            if max_history is not None:
                eligible=eligible[-int(max_history):]
            hx=x[eligible]; hy=y[eligible]
            kind,prior,model=_fit(hx,hy)
            if i == locked_start:
                frozen_fit=(kind,prior,model)
        if kind=="FITTED_PRIOR_ONLY_LOGISTIC":
            calibrated[i]=float(np.clip(model.predict_proba([[x[i]]])[0,1],EPS,1-EPS))
        else:
            calibrated[i]=float(prior)
        status.append(kind)
        training_rows.append(
            int(sum(1 for j in range(min(i,locked_start)) if pt[j] < pt[i] and mt[j] <= pt[i]))
        )

    return {
        "raw": x,
        "correctness": y,
        "calibrated": calibrated,
        "status_by_row": status,
        "training_rows_by_row": np.asarray(training_rows,dtype=int),
        "locked_start": locked_start,
        "frozen_status": frozen_fit[0],
        "frozen_training_rows": int(training_rows[locked_start]),
        "contract": {
            "status":"PASS",
            "prior_prediction_time_strict":True,
            "outcome_confirmed_at_must_be_before_or_at_target_prediction_time":True,
            "same_prediction_time_excluded":True,
            "locked_outcomes_update_calibrator":False,
        },
        "production_effect":"none",
    }


def brier(y_true, probability) -> float:
    y=np.asarray(y_true,int); p=np.clip(np.asarray(probability,float),EPS,1-EPS)
    if len(y)!=len(p): raise ValueError("brier inputs must align")
    return float(np.mean((p-y)**2))


def ece(y_true, probability, bins: int = 10) -> float:
    y=np.asarray(y_true,int); p=np.clip(np.asarray(probability,float),0.0,1.0)
    if len(y)!=len(p): raise ValueError("ece inputs must align")
    total=0.0
    edges=np.linspace(0.0,1.0,bins+1)
    for lo,hi in zip(edges[:-1],edges[1:]):
        mask=(p>=lo)&(p<hi if hi<1 else p<=hi)
        if mask.any():
            total += float(mask.mean())*abs(float(y[mask].mean())-float(p[mask].mean()))
    return float(total)


__all__=["chronological_predictability_calibration","brier","ece"]
