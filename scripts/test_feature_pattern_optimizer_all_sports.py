from __future__ import annotations

import numpy as np

from src.feature_pattern_optimizer import (
    SUPPORTED_SPORTS,
    broad_pattern_grid,
    classify_feature,
    evaluate_patterns,
)


def main() -> int:
    assert set(SUPPORTED_SPORTS) == {
        "valorant", "basketball", "volleyball", "tennis", "ufc",
        "rizin", "f1", "rugby", "boxing",
    }

    names = [
        "A__elo", "B__elo", "D__elo",
        "A__recent_winrate_5", "B__recent_winrate_20", "D__recent_winrate_5",
        "A__stat_points__mean", "B__stat_points__trend", "D__stat_points__mean",
        "A__profile__age_years", "B__profile__height", "D__profile__height",
        "A__roster__starter_count", "B__lineup_known",
        "competition_is_bleague",
        "A__availability_out", "B__availability_uncertain",
        "AD__stat_points__mean", "M__stat_points__mean", "R__recent_winrate_5",
        "D__elo__x__D__recent_winrate_20",
    ]

    assert classify_feature("A__elo") == "identity_strength"
    assert classify_feature("A__recent_winrate_5") == "form_load"
    assert classify_feature("A__stat_points__mean") == "performance_history"
    assert classify_feature("A__profile__height") == "entity_profile"
    assert classify_feature("AD__stat_points__mean") == "performance_history"

    patterns = broad_pattern_grid("basketball", names, max_patterns=384)
    assert len(patterns) >= 30
    assert len(broad_pattern_grid("basketball", names, max_patterns=1024)) >= 30
    pids = {p["pattern_id"] for p in patterns}
    assert any("profile" in p.lower() for p in pids)
    assert any("subset_" in p for p in pids)
    assert any(p["representation"] == "diff_only" for p in patterns)
    assert any(p["representation"] == "robust_summary" for p in patterns)

    rng = np.random.default_rng(42)
    n = 420
    X = rng.normal(size=(n, len(names)))
    y = (X[:, 0] + 0.6 * X[:, 3] + 0.35 * X[:, 8] + rng.normal(scale=1.0, size=n) > 0).astype(int)

    report = evaluate_patterns(
        X[:280],
        y[:280],
        names,
        "volleyball",
        start=150,
        step=25,
        max_patterns=160,
        stage2_top_k=20,
    )
    assert report["status"] == "EVALUATED"
    assert report["candidate_count"] >= 30
    assert report["stage1_ranker_candidate_count"] > 0
    assert report["stage2_candidate_count"] > 0
    assert report["selected_model_kind"] in {"hist_gb", "extra_trees"}
    assert report["baseline_aligned_to_selected_model"]["status"] == "EVALUATED"
    assert report["selected_aligned_summary"]["status"] == "EVALUATED"
    assert report["holdout_touched"] is False
    assert report["production_adoption"] == "NOT_AUTHORIZED_BY_PATTERN_SCREEN_ALONE"

    # The nine sport names must all be accepted by the search API without
    # silently routing one sport to another sport's priority.
    for sport in SUPPORTED_SPORTS:
        grid = broad_pattern_grid(sport, names, max_patterns=32)
        assert grid

    print("ALL_NINE_SPORT_FEATURE_PATTERN_SEARCH=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
