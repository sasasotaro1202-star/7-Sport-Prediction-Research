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

    legacy_future = 'SPORTS=("valorant","basketball","volleyball","tennis","ufc","rizin","f1","rugby","boxing")'
    legacy_policy = "SPORTS=('valorant','basketball','volleyball','tennis','ufc','rizin','f1','rugby','boxing')"
    assert legacy_future not in future
    assert legacy_policy not in eligibility

    print("RUNTIME_PREDICTION_SCOPE=PASS")

if __name__=="__main__":
    main()
