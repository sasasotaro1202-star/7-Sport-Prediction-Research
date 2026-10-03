#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import tempfile

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer

from src.competition_profiles import build_segment_candidates, resolve_research_profile
from src.competition_route_builder import _artifact_name, _load_event_metadata, _load_policy


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    p = _load_policy()
    assert p["research_scope"]["explicit_competition_id_required"] is True
    assert p["research_scope"]["no_implicit_production_activation"] is True
    assert p["minimums"]["holdout_rows"] >= 30
    assert p["selection"]["min_relative_logloss_improvement"] >= 0.03
    assert p["selection"]["bootstrap_probability_improvement"] >= 0.90
    assert "competition_specific_accepted" in p["fallback_chain"]

    profile = resolve_research_profile("basketball", "EuroLeague 2026", "league match")
    segments = build_segment_candidates(
        profile,
        sport="basketball",
        season="2026-27",
        stage="playoff",
        round_="quarterfinal",
        event_type="match",
    )
    assert [x["specificity"] for x in segments] == [4, 3, 2, 1, 0]
    assert segments[0]["segment_id"].endswith(
        "::season=2026-27::stage=playoff::round=quarterfinal::event_type=match"
    )
    assert segments[-1]["segment_id"] == profile["profile_id"]
    assert segments[0]["context"]["stage"] == "playoff"

    research = resolve_research_profile("basketball", "EuroLeague 2026", "league match")
    assert research["matched"] is True
    assert research["dynamic"] is True
    assert research["profile_id"] == "basketball:competition:euroleague_2026"

    temp = Path(tempfile.mkdtemp(prefix="competition-route-"))
    model = Pipeline([("i", SimpleImputer(strategy="median")), ("m", LogisticRegression(max_iter=2000))])
    X = np.array([[0.1], [0.9], [0.2], [0.8]], dtype=float)
    y = np.array([0, 1, 0, 1], dtype=int)
    model.fit(X, y)
    path = temp / _artifact_name("basketball:competition:euroleague_2026")
    joblib.dump(model, path)
    loaded = joblib.load(path)
    assert loaded.predict_proba(X).shape == (4, 2)

    # Canonical v45 schema regression: event has competition_id but no display name.
    import sqlite3
    from src.storage.db_v45 import SCHEMA, _migrate
    db = temp / "sports_v45.sqlite"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    _migrate(con)
    con.execute(
        "INSERT INTO event(event_id,sport,competition_id,season,stage,event_time_utc,quality_status) VALUES (?,?,?,?,?,?,?)",
        ("e1", "basketball", "B.LEAGUE", "2025-26", "league", "2026-01-01T00:00:00+00:00", "VERIFIED"),
    )
    con.commit()
    metadata = _load_event_metadata(con, "basketball")
    con.close()
    assert metadata["e1"]["competition_id"] == "B.LEAGUE"
    assert metadata["e1"]["season"] == "2025-26"
    assert metadata["e1"]["stage"] == "league"
    assert "name" not in metadata["e1"]


    # Most-specific accepted route must win, while a missing leaf route must
    # deterministically fall back to its broader ancestor.
    import src.competition_route_registry as registry
    with tempfile.TemporaryDirectory() as td:
        troot = Path(td)
        artifact_dir = troot / "models" / "competition"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_specific = artifact_dir / "specific.joblib"
        artifact_broad = artifact_dir / "broad.joblib"
        joblib.dump(model, artifact_specific)
        joblib.dump(model, artifact_broad)
        original_root = registry.ROOT
        original_allowed = registry._allowed_sports
        original_load = registry.load_registry
        registry.ROOT = troot
        registry._allowed_sports = lambda: {"basketball"}
        segments = build_segment_candidates(
            profile,
            sport="basketball",
            season="2026-27",
            stage="playoff",
            round_="quarterfinal",
            event_type="match",
        )
        registry.load_registry = lambda: {
            "status": "READY",
            "routes": {
                segments[-2]["segment_id"]: {
                    "quality_status": "ACCEPTED_LOCKED_HOLDOUT",
                    "model_scope": "competition_specific;frozen_holdout_accepted",
                    "sport": "basketball",
                    "profile_id": profile["profile_id"],
                    "segment_id": segments[-2]["segment_id"],
                    "segment_specificity": segments[-2]["specificity"],
                    "artifact_path": "models/competition/broad.joblib",
                    "git_commit_sha": "test-sha",
                    "holdout_used_for_selection": False,
                    "holdout": {"n": 30},
                },
                segments[0]["segment_id"]: {
                    "quality_status": "ACCEPTED_LOCKED_HOLDOUT",
                    "model_scope": "competition_specific;frozen_holdout_accepted",
                    "sport": "basketball",
                    "profile_id": profile["profile_id"],
                    "segment_id": segments[0]["segment_id"],
                    "segment_specificity": segments[0]["specificity"],
                    "artifact_path": "models/competition/specific.joblib",
                    "git_commit_sha": "test-sha",
                    "holdout_used_for_selection": False,
                    "holdout": {"n": 30},
                },
            },
        }
        resolved = registry.resolve_route(
            "basketball",
            profile,
            {
                "season": "2026-27",
                "stage": "playoff",
                "round": "quarterfinal",
                "event_type": "match",
            },
        )
        assert resolved is not None
        assert resolved["route"]["segment_id"] == segments[0]["segment_id"]
        assert resolved["routing_depth"] == 4
        registry.load_registry = lambda: {
            "status": "READY",
            "routes": {
                segments[-2]["segment_id"]: {
                    "quality_status": "ACCEPTED_LOCKED_HOLDOUT",
                    "model_scope": "competition_specific;frozen_holdout_accepted",
                    "sport": "basketball",
                    "profile_id": profile["profile_id"],
                    "segment_id": segments[-2]["segment_id"],
                    "segment_specificity": segments[-2]["specificity"],
                    "artifact_path": "broad.joblib",
                    "git_commit_sha": "test-sha",
                    "holdout_used_for_selection": False,
                    "holdout": {"n": 30},
                },
            },
        }
        resolved = registry.resolve_route(
            "basketball",
            profile,
            {
                "season": "2026-27",
                "stage": "playoff",
                "round": "quarterfinal",
                "event_type": "match",
            },
        )
        assert resolved is not None
        assert resolved["route"]["segment_id"] == segments[-2]["segment_id"]
        assert resolved["routing_depth"] == 1
        registry.load_registry = original_load
        registry._allowed_sports = original_allowed
        registry.ROOT = original_root

    future_src = (ROOT / "src/future_predictor.py").read_text(encoding="utf-8")
    assert "competition_route" in future_src
    assert "competition_specific_model" in future_src
    assert "round_,event_type" in future_src
    assert '"segment_specificity"' in future_src
    assert '"most_specific_segment"' in future_src
    route_builder_src = (ROOT / "src/competition_route_builder.py").read_text(encoding="utf-8")
    assert "build_segment_candidates" in route_builder_src
    assert '"segment_id"' in route_builder_src

    workflow = (ROOT / ".github/workflows/v4_5_15_production.yml").read_text(encoding="utf-8")
    assert "src.competition_route_builder" in workflow
    assert "python -m src.competition_route_builder" in workflow

    print("COMPETITION_SPECIFIC_ROUTING=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
