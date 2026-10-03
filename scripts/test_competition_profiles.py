#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from src.competition_profiles import resolve_profile, profile_policy


def main() -> int:
    assert resolve_profile("basketball", "B.LEAGUE", "league match")["profile_id"] == "basketball:bleague"
    assert resolve_profile("basketball", "Asian Games", "Asian Games Basketball")["profile_id"] == "basketball:asian_games"
    assert resolve_profile("volleyball", "Asian Games Volleyball", "match")["profile_id"] == "volleyball:asian_games"
    ufc = resolve_profile("ufc", "UFC", "UFC 300")
    assert ufc["phase_type"] == "promotion"
    assert ufc["canonical_competition_id"] == "ufc:promotion"
    rizin = resolve_profile("rizin", "RIZIN", "RIZIN 1")
    assert rizin["canonical_competition_id"] == "rizin:promotion"

    unknown = resolve_profile("basketball", "", "ordinary unknown competition")
    assert unknown["matched"] is False
    assert resolve_profile("basketball", "B.LEAGUE\n", "league match")["canonical_competition_id"] == "basketball:bleague"
    dynamic = resolve_profile("valorant", "VCT Champions 2026", "team match")
    assert dynamic["matched"] is True
    assert dynamic["dynamic"] is True
    assert dynamic["profile_id"] == "valorant:competition:vct_champions_2026"
    assert dynamic["canonical_competition_id"] == "valorant:competition:vct_champions_2026"
    policy = profile_policy()
    assert policy["no_implicit_pooling"] is True
    assert policy["production_route_enabled"] is False
    assert "valorant" in policy["dynamic_competition_discovery"]
    assert policy["selection"]["require_holdout_before_production"] is True
    # Regression: the event schema has no `name` column. Competition OOS must
    # read only canonical schema fields and still resolve explicit competition IDs.
    import json
    import sys
    import tempfile
    from src.storage.db_v45 import SCHEMA, _migrate
    import src.competition_profile_oos as competition_oos
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "sports_v45.sqlite"
        out_path = Path(td) / "competition_profiles.json"
        import sqlite3
        con = sqlite3.connect(db_path)
        con.executescript(SCHEMA)
        _migrate(con)
        con.execute(
            "INSERT INTO event(event_id,sport,competition_id,season,stage,event_time_utc,quality_status) VALUES (?,?,?,?,?,?,?)",
            ("e1", "basketball", "B.LEAGUE", "2025-26", "league", "2026-01-01T00:00:00+00:00", "VERIFIED"),
        )
        con.commit()
        con.close()
        original_build = competition_oos.base.build
        competition_oos.base.build = lambda _con, _sport: (
            [("e1", "2026-01-01T00:00:00+00:00", 1, {})],
            [],
        )
        try:
            old_argv = sys.argv
            sys.argv = [
                "competition_profile_oos.py",
                "--sport", "basketball",
                "--db", str(db_path),
                "--out", str(out_path),
            ]
            rc = competition_oos.main()
        finally:
            sys.argv = old_argv
            competition_oos.base.build = original_build
        assert rc == 0, "competition profile OOS schema regression failed"
        report = json.loads(out_path.read_text(encoding="utf-8"))
        assert report["failures"] == []
        profile = report["sports"]["basketball"]["basketball:bleague"]
        assert profile["profile"]["matched"] is True
        assert profile["profile"]["competition_id"] == "B.LEAGUE"

    gate = (Path(__file__).resolve().parents[1] / "src/production_release_gate.py").read_text(encoding="utf-8")
    assert "meta.setdefault('sport',sport)" in gate
    print("COMPETITION_PROFILE_RESOLVER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
