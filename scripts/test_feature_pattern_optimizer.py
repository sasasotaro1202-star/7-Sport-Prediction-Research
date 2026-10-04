from __future__ import annotations

import numpy as np

from src.feature_pattern_optimizer import (
    candidate_family_sets,
    classify_feature,
    evaluate_patterns,
)


def main() -> int:
    names = [
        "A__elo",
        "B__elo",
        "D__elo",
        "A__recent_winrate_5",
        "B__recent_winrate_5",
        "D__recent_winrate_5",
        "A__stat_sig_str__mean",
        "B__stat_sig_str__mean",
        "D__stat_sig_str__mean",
        "A__profile__height",
        "B__profile__height",
        "D__profile__height",
        "A__team__lineup_count",
        "D__team__lineup_count",
        "competition_is_bleague",
        "weather_signal_count",
        "D__elo_x_form",
    ]
    assert classify_feature("A__elo") == "identity_strength"
    assert classify_feature("A__recent_winrate_5") == "form_load"
    assert classify_feature("A__profile__height") == "entity_profile"
    assert classify_feature("A__stat_sig_str__mean") == "performance_history"
    candidates = candidate_family_sets("basketball", names, max_patterns=12)
    assert len(candidates) >= 4
    assert any("entity_profile" in x["families"] for x in candidates)

    rng = np.random.default_rng(42)
    n = 360
    X = rng.normal(size=(n, len(names)))
    y = (X[:, 0] + 0.4 * X[:, 3] + rng.normal(scale=1.0, size=n) > 0).astype(int)
    report = evaluate_patterns(
        X,
        y,
        names,
        "basketball",
        start=160,
        step=40,
        max_patterns=10,
    )
    assert report["status"] == "EVALUATED"
    assert report["candidate_count"] >= 3
    assert report["holdout_touched"] is False
    assert report["selected_pattern_id"] in report["results"]
    print("FEATURE_PATTERN_OPTIMIZER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
