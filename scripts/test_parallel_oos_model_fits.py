import numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from src.research_cycle_strict import _fit_predict_oos_models_parallel

rng = np.random.default_rng(20260925)
X = rng.normal(size=(180, 8))
X[rng.random(X.shape) < 0.08] = np.nan
y = (X[:, 0] + np.nan_to_num(X[:, 1]) * 0.4 > 0).astype(int)

def make_models():
    return {
        "et": Pipeline([
            ("i", SimpleImputer(strategy="median")),
            ("m", ExtraTreesClassifier(n_estimators=30, min_samples_leaf=2, random_state=42, n_jobs=-1)),
        ]),
        "hgb": Pipeline([
            ("i", SimpleImputer(strategy="median")),
            ("m", HistGradientBoostingClassifier(max_iter=30, random_state=43)),
        ]),
    }

names = ["et", "hgb"]
parallel_pool = make_models()
parallel = _fit_predict_oos_models_parallel(parallel_pool, names, X[:120], y[:120], X[120:])

serial = {}
for name, model in make_models().items():
    model.fit(X[:120], y[:120])
    serial[name] = np.clip(model.predict_proba(X[120:])[:, 1], 1e-6, 1 - 1e-6)

for name in names:
    assert np.allclose(parallel[name], serial[name], atol=1e-12, rtol=0), name
print("parallel OOS fit equivalence: PASS")
