from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src import trajectory_intelligence_oos as ti

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def fixture(n=48):
    rows, outcomes = [], {}
    for i in range(n):
        event = BASE + timedelta(hours=3 * i)
        group = i % 2
        eid = f"e{i}"
        outcomes[eid] = {"outcome": group, "outcome_status": "VERIFIED"}
        for minute in (-180, -120, -60, -30):
            pt = event + timedelta(minutes=minute)
            rows.append({
                "event_id": eid,
                "event_time_utc": event.isoformat(),
                "prediction_time_utc": pt.isoformat(),
                "source_available_at_utc": (pt - timedelta(minutes=5)).isoformat(),
                "feature_vector": [group, i % 5, minute],
                "observed_state_vector": [group * 2 + minute / 1800, group],
            })
    return rows, outcomes


def test_pit_fail_closed():
    rows, _ = fixture(1)
    rows[0] = dict(rows[0])
    rows[0]["source_available_at_utc"] = (BASE + timedelta(days=1)).isoformat()
    out = ti.validate_snapshots(rows[:1])
    assert out["status"] == "PIT_INVALID_INPUT"
    assert out["valid_rows"] == 0


def test_in_event_contract():
    rows, _ = fixture(1)
    row = dict(rows[0])
    event = datetime.fromisoformat(row["event_time_utc"])
    row["prediction_time_utc"] = (event + timedelta(minutes=10)).isoformat()
    row["event_end_time_utc"] = (event + timedelta(minutes=120)).isoformat()
    assert ti.validate_snapshots([row], mode="in_event")["status"] == "PASS"


def test_event_canonicalization_and_folds():
    rows, outcomes = fixture()
    valid = ti.validate_snapshots(rows)
    built = ti.build_trajectory_cases(valid["snapshots"], outcomes, [3600, 5400])
    canonical = ti.canonical_event_cases(built["cases"])
    assert len(canonical) == 48
    folds = ti.chronological_event_folds(canonical, n_folds=6, min_train_events=12)
    assert len(folds) == 6
    seen = set()
    pos = {c.event_id: i for i, c in enumerate(canonical)}
    for fold in folds:
        train, test = set(fold["train_event_ids"]), set(fold["test_event_ids"])
        assert not train & test
        assert not seen & test
        seen |= test
        assert max(pos[x] for x in train) < min(pos[x] for x in test)


def test_future_features_do_not_leak_into_anchor():
    rows, outcomes = fixture(24)
    a = ti.build_trajectory_cases(ti.validate_snapshots(rows)["snapshots"], outcomes, [3600, 5400])
    mutated = []
    for row in rows:
        item = dict(row)
        event_time = datetime.fromisoformat(row["event_time_utc"])
        earliest_anchor = event_time - timedelta(minutes=180)
        if datetime.fromisoformat(row["prediction_time_utc"]) > earliest_anchor:
            # Only later snapshots are mutated; the canonical earliest anchor stays identical.
            item["feature_vector"] = [999999.0, -999999.0, 1]
        mutated.append(item)
    b = ti.build_trajectory_cases(ti.validate_snapshots(mutated)["snapshots"], outcomes, [3600, 5400])
    ca, cb = ti.canonical_event_cases(a["cases"]), ti.canonical_event_cases(b["cases"])
    assert [x.anchor_features.tolist() for x in ca] == [x.anchor_features.tolist() for x in cb]


def test_oos_and_scenario_output():
    rows, outcomes = fixture()
    built = ti.build_trajectory_cases(ti.validate_snapshots(rows)["snapshots"], outcomes, [3600, 5400])
    result = ti.evaluate_oos(built["cases"], n_folds=6, min_train_events=12, k=9)
    assert result["status"] == "EVALUATED"
    assert result["promotion_status"] == "RESEARCH_ONLY_NO_AUTO_PROMOTION"
    memory = ti.EmpiricalTrajectoryMemory(k=9).fit(ti.canonical_event_cases(built["cases"][:72]))
    forecast = memory.predict([1.0, 1.0, -180.0], event_id="future")
    assert forecast["status"] == "FORECAST_AVAILABLE"
    assert abs(sum(forecast["scenario_weights"]) - 1.0) < 1e-9
    assert set(forecast["outcome_probability_by_horizon"]) == {"3600", "5400"}


if __name__ == "__main__":
    for name in sorted(globals()):
        if name.startswith("test_"):
            globals()[name]()
    print("TRAJECTORY_INTELLIGENCE_OOS_TEST=PASS")
