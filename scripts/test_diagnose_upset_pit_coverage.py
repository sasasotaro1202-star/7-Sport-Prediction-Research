import sqlite3

import scripts.diagnose_upset_pit_coverage as diag


class _FakeCursor:
    def fetchone(self):
        return (17,)

    def fetchall(self):
        return []


class _FakeConnection:
    def execute(self, *_args, **_kwargs):
        return _FakeCursor()


def test_diagnostic_reports_zero_strict_rows_as_blocking(monkeypatch):
    monkeypatch.setattr(diag.base, "pairmap", lambda con, sport: {
        "e1": {"time": "2026-01-01T00:00:00+00:00", "A": "a", "B": "b"}
    })
    monkeypatch.setattr(
        diag.base,
        "outcome_maps",
        lambda con, sport, pairs: ({"e1": "A"}, [("e1", "2026-01-01T00:00:00+00:00", "a", "b", "A", "2026-01-02T00:00:00+00:00")]),
    )
    monkeypatch.setattr(diag.base, "statcols", lambda con, sport: ["x", "y"])
    monkeypatch.setattr(diag.base, "build", lambda con, sport: ([], ["A__x", "B__x"]))
    monkeypatch.setattr(diag, "_accepted_artifact", lambda sport: ({"quality_status": "ACCEPTED_LOCKED_HOLDOUT"}, None))

    payload = diag.diagnose(_FakeConnection(), "basketball")

    assert payload["status"] == "DIAGNOSTIC_ONLY"
    assert payload["pair_events"] == 1
    assert payload["complete_pair_events"] == 1
    assert payload["verified_outcome_events"] == 1
    assert payload["historical_outcome_rows"] == 1
    assert payload["eligible_strict_pit_rows_exact_build"] == 0
    assert payload["exact_provenance_match_stats_rows"] == 17
    assert payload["blocking_interpretation"].startswith("base.build() produced no rows")
    assert payload["production_effect"] == "none"


def test_diagnostic_does_not_modify_connection_or_model_state(monkeypatch):
    monkeypatch.setattr(diag.base, "pairmap", lambda con, sport: {})
    monkeypatch.setattr(diag.base, "outcome_maps", lambda con, sport, pairs: ({}, []))
    monkeypatch.setattr(diag.base, "statcols", lambda con, sport: [])
    monkeypatch.setattr(diag.base, "build", lambda con, sport: ([], []))
    monkeypatch.setattr(diag, "_accepted_artifact", lambda sport: (None, "missing_artifact"))

    payload = diag.diagnose(_FakeConnection(), "ufc")

    assert payload["accepted_artifact_present"] is False
    assert payload["accepted_artifact_reason"] == "missing_artifact"
    assert payload["eligible_strict_pit_rows_exact_build"] == 0
