import numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

rng = np.random.default_rng(20260925)
X = rng.normal(size=(220, 10))
X[:, 2] = np.nan
X[:, 7] = np.nan
X[:30, 9] = np.nan
y = (np.nan_to_num(X[:, 0]) + 0.4 * np.nan_to_num(X[:, 1]) > 0).astype(int)

keep = np.isfinite(X[:150]).any(axis=0)
assert not keep[2] and not keep[7]
assert keep[9]

models = [
    Pipeline([
        ("i", SimpleImputer(strategy="median")),
        ("m", ExtraTreesClassifier(n_estimators=50, min_samples_leaf=2, random_state=42, n_jobs=1)),
    ]),
    Pipeline([
        ("i", SimpleImputer(strategy="median")),
        ("m", HistGradientBoostingClassifier(max_iter=40, random_state=43)),
    ]),
]

for m in models:
    m.fit(X[:150], y[:150])
    baseline = m.predict_proba(X[150:])[:, 1]
    m2 = type(m)(steps=[(name, step) for name, step in m.steps])
    m2.fit(X[:150, keep], y[:150])
    pruned = m2.predict_proba(X[150:, keep])[:, 1]
    assert np.allclose(baseline, pruned, atol=1e-12, rtol=0), type(m).__name__

print("fold-local all-missing feature pruning equivalence: PASS")
