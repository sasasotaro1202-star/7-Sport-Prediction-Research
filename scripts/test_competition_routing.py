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

from src.competition_profiles import resolve_research_profile
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

    # Regression: canonical v45 event schema intentionally has no display-name
    # column. The route builder must resolve identity from explicit competition_id.
    from src.storage.db_v45 import SCHEMA, _migrate
    import sqlite3
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

    future_src = (ROOT / "src/future_predictor.py").read_text(encoding="utf-8")
    assert "competition_route" in future_src
    assert "competition_specific_model" in future_src

    workflow = (ROOT / ".github/workflows/v4_5_15_production.yml").read_text(encoding="utf-8")
    assert "src.competition_route_builder" in workflow
    assert "python -m src.competition_route_builder" in workflow

    print("COMPETITION_SPECIFIC_ROUTING=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
