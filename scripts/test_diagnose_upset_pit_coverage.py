from scripts import diagnose_upset_pit_coverage as diag


class FakeResult:
    def __getitem__(self, index):
        return (7,)[index]


class FakeConnection:
    def execute(self, *args, **kwargs):
        return FakeResult()


def test_diagnostic_contract(monkeypatch):
    monkeypatch.setattr(diag.base, "pairmap", lambda con, sport: {"e1": {"A": "a", "B": "b"}})
    monkeypatch.setattr(
        diag.base,
        "outcome_maps",
        lambda con, sport, pairs: ({"e1": "A"}, [("e1", "2026-01-01T00:00:00+00:00", "a", "b", "A", "2026-01-01T01:00:00+00:00")]),
    )
    monkeypatch.setattr(diag.base, "statcols", lambda con, sport: ["s1"])
    monkeypatch.setattr(diag.base, "build", lambda con, sport: ([(1, "t", 0, {})], ["s1"]))
    monkeypatch.setattr(diag, "_accepted_artifact", lambda sport: ({"quality_status": "ACCEPTED_LOCKED_HOLDOUT"}, None))

    out = diag.diagnose(FakeConnection(), "basketball")
    assert out["status"] == "DIAGNOSTIC_ONLY"
    assert out["pair_events"] == 1
    assert out["complete_pair_events"] == 1
    assert out["verified_outcome_events"] == 1
    assert out["historical_outcome_rows"] == 1
    assert out["eligible_strict_pit_rows_exact_build"] == 1
    assert out["feature_columns_exact_build"] == 1
    assert out["configured_stat_names"] == ["s1"]
    assert out["exact_provenance_match_stats_rows"] == 7
    assert out["accepted_artifact_present"] is True
    assert out["production_effect"] == "none"
