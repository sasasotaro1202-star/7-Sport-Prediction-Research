from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "results/research/bleague_public_availability_shadow_audit.json"


def main() -> None:
    assert REPORT.is_file() and REPORT.stat().st_size > 0
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert report["version"] == "bleague-public-availability-shadow-audit-v1"
    assert report["status"] == "SHADOW_AUDIT_COMPLETED"
    assert report["scope"]["sport"] == "basketball"
    assert report["scope"]["competition"] == "B.LEAGUE"
    assert report["scope"]["prediction_cutoff_policy"] == "T-60"

    evidence = report["evidence"]
    assert evidence["strict_pit_usable"] is False
    assert evidence["revision_sha"] == "42c621a5437228a4d5a796f62116bee5cc44dce2"
    assert evidence["public_availability_bound_utc"] == "2021-04-19T23:59:59Z"
    assert evidence["next_file_touch_sha"] == "64cba9d4693646b3365805da04ad9f8779e5233c"
    assert evidence["matched_current_rows_in_pinned_revision"] >= 0
    assert len(evidence["pinned_content_sha256"]) == 64
    assert len(evidence["current_content_sha256"]) == 64

    candidate = report["candidate_pit"]
    for key in (
        "matched_events_present_in_db",
        "exact_feature_vector_events",
        "exact_feature_stat_rows",
        "matched_events_missing_from_db",
        "candidate_target_events_total",
        "candidate_target_events_cutoff_at_or_after_bound",
        "candidate_targets_with_any_exact_history",
        "candidate_targets_with_both_team_exact_history",
        "candidate_prior_history_observations",
    ):
        assert isinstance(candidate[key], int) and candidate[key] >= 0

    assert candidate["exact_feature_vector_events"] <= candidate["matched_events_present_in_db"]
    assert candidate["matched_events_present_in_db"] <= evidence["matched_current_rows_in_pinned_revision"]

    safety = report["safety"]
    assert all(safety[name] is False for name in (
        "database_mutation",
        "source_snapshot_promotion",
        "match_stats_repoint",
        "production_model_change",
        "route_change",
        "probability_change",
        "holdout_change",
        "strict_pit_acceptance_change",
        "promotion_allowed",
    ))
    print("BLEAGUE_PUBLIC_AVAILABILITY_SHADOW_AUDIT=PASS")


if __name__ == "__main__":
    main()
