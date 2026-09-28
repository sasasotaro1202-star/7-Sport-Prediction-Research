"""Regression test: runtime prediction scope must come from the formal project scope policy."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

def main():
    policy=json.loads((ROOT/"config/PROJECT_SCOPE_POLICY.json").read_text(encoding="utf-8"))
    expected=["basketball","volleyball","ufc","rizin","valorant"]
    assert policy["active_prediction_scope"]==expected

    future=(ROOT/"src/future_predictor.py").read_text(encoding="utf-8")
    eligibility=(ROOT/"src/prediction_policy.py").read_text(encoding="utf-8")
    latest=(ROOT/"src/latest_prediction.py").read_text(encoding="utf-8")

    assert "PROJECT_SCOPE_POLICY.json" in future
    assert "PROJECT_SCOPE_POLICY.json" in eligibility
    assert "active_prediction_scope" in latest

    forbidden=("soccer","baseball","tennis","f1","rugby","boxing")
    for src in (future,eligibility,latest):
        # Legacy helper names are acceptable, but runtime sport lists must not hard-code
        # a forbidden active prediction target set.
        assert 'SPORTS=(' not in src or not any(f in src for f in forbidden)

    print("RUNTIME_PREDICTION_SCOPE=PASS")

if __name__=="__main__":
    main()
