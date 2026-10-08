import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "prediction_core_oss_candidates.json"
REQ = ROOT / "requirements.txt"

EXPECTED = {
    "pymc-devs/pymc", "optuna/optuna", "online-ml/river", "deepcharles/ruptures",
    "catboost/catboost", "dmlc/xgboost", "Nixtla/statsforecast",
    "Nixtla/neuralforecast", "google-research/timesfm", "unit8co/darts",
    "sktime/sktime", "arviz-devs/arviz",
}

data = json.loads(REGISTRY.read_text(encoding="utf-8"))
assert data["status"] == "RESEARCH_REGISTRY_ONLY"
assert data["production_dependency"] is False
assert data["auto_promotion"] is False

candidates = data["candidates"]
assert len(candidates) == 12
assert {item["repository"] for item in candidates} == EXPECTED
assert [item["rank"] for item in candidates] == list(range(1, 13))
assert len({item["verified_commit"] for item in candidates}) == 12

for item in candidates:
    assert item["scope"] == "research_only"
    assert item["status"] in {"PROMOTION_CANDIDATE", "RESEARCH_CANDIDATE"}
    assert item["verified_commit"]
    assert item["license"]
    assert item["gates"]

requirements = REQ.read_text(encoding="utf-8").lower()
for name in (
    "pymc", "optuna", "river", "ruptures", "catboost", "xgboost",
    "statsforecast", "neuralforecast", "timesfm", "darts", "sktime", "arviz"
):
    assert name not in requirements, f"unexpected production dependency: {name}"

print("PREDICTION_CORE_OSS_REGISTRY=PASS")

cfg_path = ROOT / "config" / "prediction_core_oss_candidates.json"
import json
cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
assert cfg["automatic_promotion"] is False
assert cfg["registry_semantics"]["promotion_status"] == "explicit production decision boundary"
for candidate in cfg["candidates"]:
    assert candidate["promotion_status"] == "HOLD"
