from __future__ import annotations

from pathlib import Path


def main() -> None:
    src = (Path(__file__).resolve().parents[1] / "src" / "research_cycle_strict.py").read_text(encoding="utf-8")
    assert "hold_probability_calibrated=base.metric(y_holdout,calibrated_hold_p)" in src
    assert "router_holdout_models[name].predict_proba(X_holdout)" in src
    assert "router_holdout_models[name].predict_proba(X[sel:])" not in src
    print("RESEARCH_CYCLE_STRICT_HOLDOUT_PARTITION=PASS")


if __name__ == "__main__":
    main()
