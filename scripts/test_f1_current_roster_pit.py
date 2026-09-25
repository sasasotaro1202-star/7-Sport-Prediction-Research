from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import src.future_predictor as fp
from src.storage.db_v45 import SCHEMA
from src.seven_sport_production import upsert_event


class _Resp:
    def __init__(self, text):
        self._text = text
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self._text.encode("utf-8")


def test_current_roster_parsing_and_f1_fallback(monkeypatch):
    names = [
        "George Russell", "Kimi Antonelli", "Charles Leclerc", "Lewis Hamilton",
        "Lando Norris", "Oscar Piastri", "Max Verstappen", "Isack Hadjar",
        "Liam Lawson", "Arvid Lindblad", "Pierre Gasly", "Franco Colapinto",
        "Esteban Ocon", "Oliver Bearman", "Nico Hulkenberg", "Gabriel Bortoleto",
        "Carlos Sainz", "Alexander Albon", "Fernando Alonso", "Lance Stroll",
        "Sergio Perez", "Valtteri Bottas",
    ]
    html = "".join(
        f'<a href="/en/drivers/{name.lower().replace(" ", "-")}">{name}</a>'
        for name in names
    )
    calls = {"n": 0}
    def fake_urlopen(req, timeout=15):
        calls["n"] += 1
        return _Resp(html)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    fp._F1_ROSTER_CACHE = None

    now = datetime.now(timezone.utc)
    roster = fp._current_f1_roster(now)
    assert roster is not None
    retrieved, parsed = roster
    assert retrieved <= now + timedelta(seconds=1)
    assert parsed == names
    assert calls["n"] == 1

    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    event_time = now + timedelta(hours=3)
    eid = upsert_event(
        con, "f1", "Future Singapore Test", event_time.isoformat(),
        "jolpica", "https://api.jolpi.ca/ergast/f1/2026/17/", "SCHEDULED",
        "F1", "2026", None, "17"
    )
    con.commit()

    out = fp._safe_prior_f1(con, now)
    assert out["status"] == "PREDICTED_SAFE_PRIOR_MULTICLASS"
    assert out["count"] == 1
    pred = out["predictions"][0]
    assert pred["field_source"] == "FORMULA1_OFFICIAL_CURRENT_DRIVER_ROSTER"
    assert pred["field_status"] == "CURRENT_ROSTER_NOT_EVENT_CONFIRMED"
    assert pred["confidence"] == "LOW"
    assert len(pred["drivers"]) == 22
    assert abs(sum(x["probability"] for x in pred["drivers"]) - 1.0) < 1e-9
    assert eid == pred["event_id"]
    con.close()


if __name__ == "__main__":
    test_current_roster_parsing_and_f1_fallback(
        __import__("pytest").MonkeyPatch()
    )
    print("f1 current roster PIT fallback test: PASS")
