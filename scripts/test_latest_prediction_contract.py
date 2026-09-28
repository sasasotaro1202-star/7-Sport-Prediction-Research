"""Regression tests for the canonical fresh-prediction request contract."""

from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[1]


def main():
    policy = json.loads(
        (ROOT / "config/PREDICTION_FRESHNESS_POLICY.json").read_text(encoding="utf-8")
    )
    scope = json.loads(
        (ROOT / "config/PROJECT_SCOPE_POLICY.json").read_text(encoding="utf-8")
    )
    src = (ROOT / "src/latest_prediction.py").read_text(encoding="utf-8")

    assert policy["refresh_before_every_prediction_request"] is True
    assert policy["reuse_stored_prediction_output"] is False
    assert policy["stale_output_action"] == "FAIL_CLOSED"

    active = scope["active_prediction_scope"]
    assert active
    assert "soccer" not in active
    assert "baseball" not in active

    # The canonical entrypoint must refresh first and infer second.
    collect_pos = src.index("src.seven_sport_production")
    predict_pos = src.index("src.future_predictor")
    assert collect_pos < predict_pos

    required = (
        "request_started_at_utc",
        "STALE_COLLECTION_REPORT",
        "STALE_PREDICTION_REPORT",
        "COLLECTION_FAILED",
        "OUT_OF_SCOPE",
        "stored_prediction_reused",
        "FRESH_REQUEST_VERIFIED",
        "force_refresh=True",
        "V45_FORCE_REFRESH",
    )
    for marker in required:
        assert marker in src, marker

    # Stored prediction output is verification evidence only, never a stale fallback.
    assert "PREDICTION_REPORT" in src
    assert "reuse_stored_prediction_output" in src

    print("LATEST_PREDICTION_CONTRACT=PASS")


if __name__ == "__main__":
    main()
