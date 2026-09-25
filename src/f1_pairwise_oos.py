from __future__ import annotations

"""Research-only Formula 1 pairwise OOS benchmark.

The production F1 winner is intentionally still gated because a true race winner
is multiclass. This benchmark converts each race into driver-vs-driver outcomes
and predicts them from strictly pre-race driver state, then evaluates a frozen
final race block. Historical results are retrieved from the free Jolpica API.

No post-race variables (finish position, points from the current race, fastest
lap, etc.) are used as features for that race.
"""

import json
import math
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from itertools import combinations

import numpy as np
import requests
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/research/f1_pairwise_oos.json"
BASE = "https://api.jolpi.ca/ergast/f1"


def get_json(url: str) -> dict:
    last = None
    for attempt in range(5):
        try:
            r = requests.get(url, headers={"User-Agent": "SevenSportResearchEngine/4.7"}, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 4:
                raise
            time.sleep(1.5 * (2 ** attempt))


def fetch_seasons(start_year=2018, end_year=None):
    if end_year is None:
        end_year = datetime.now(timezone.utc).year
    races = []
    for year in range(start_year, end_year + 1):
        url = f"{BASE}/{year}/results.json?limit=1000"
        payload = get_json(url)
        season_races = payload.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        races.extend(season_races)
    return races


def _num(v, default=np.nan):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def build_pairwise_rows(races):
    # States are updated only after each completed race.
    elo = defaultdict(lambda: 1500.0)
    ctor_elo = defaultdict(lambda: 1500.0)
    finish_hist = defaultdict(lambda: deque(maxlen=10))
    dnf_hist = defaultdict(lambda: deque(maxlen=10))
    circuit_hist = defaultdict(lambda: defaultdict(lambda: deque(maxlen=8)))

    out = []
    for race in sorted(races, key=lambda r: (int(r.get("season", 0)), int(r.get("round", 0)))):
        season = int(race.get("season", 0))
        rnd = int(race.get("round", 0))
        race_name = str(race.get("raceName") or "")
        circuit = str((race.get("Circuit") or {}).get("circuitId") or "")
        results = []
        for rr in race.get("Results") or []:
            did = str((rr.get("Driver") or {}).get("driverId") or "")
            if not did:
                continue
            try:
                pos = float(rr.get("position"))
            except Exception:
                continue
            ctor = str((rr.get("Constructor") or {}).get("constructorId") or "")
            status = str(rr.get("status") or "").lower()
            finished = ("finished" in status) or status == "lap" or status == ""
            results.append({
                "driver": did,
                "constructor": ctor,
                "position": pos,
                "grid": _num(rr.get("grid")),
                "points": _num(rr.get("points"), 0.0),
                "dnf": 0 if finished else 1,
            })
        if len(results) < 2:
            continue

        for a, b in combinations(results, 2):
            da, db = a["driver"], b["driver"]
            ha = list(finish_hist[da]); hb = list(finish_hist[db])
            ca = list(circuit_hist[da][circuit]); cb = list(circuit_hist[db][circuit])
            fa = list(dnf_hist[da]); fb = list(dnf_hist[db])
            xa = [
                elo[da] - elo[db],
                ctor_elo[a["constructor"]] - ctor_elo[b["constructor"]],
                (np.mean(ha) if ha else np.nan) - (np.mean(hb) if hb else np.nan),
                (np.mean(ha[-5:]) if ha else np.nan) - (np.mean(hb[-5:]) if hb else np.nan),
                (np.mean(fa) if fa else np.nan) - (np.mean(fb) if fb else np.nan),
                (np.mean(ca) if ca else np.nan) - (np.mean(cb) if cb else np.nan),
                (_num(a["grid"]) if np.isfinite(_num(a["grid"])) else np.nan)
                  - (_num(b["grid"]) if np.isfinite(_num(b["grid"])) else np.nan),
            ]
            y = 1 if a["position"] < b["position"] else 0
            out.append({
                "season": season, "round": rnd, "race": race_name, "circuit": circuit,
                "driver_a": da, "driver_b": db, "y": y, "x": xa,
            })
            # Symmetric orientation increases sample efficiency without adding information.
            out.append({
                "season": season, "round": rnd, "race": race_name, "circuit": circuit,
                "driver_a": db, "driver_b": da, "y": 1-y, "x": [-v if np.isfinite(v) else np.nan for v in xa],
            })

        # Update state only after all pairwise predictions for the race have been created.
        for rr in results:
            d = rr["driver"]
            c = rr["constructor"]
            current = elo[d]
            actual_w = sum(1 for z in results if z["position"] > rr["position"])
            expected_w = sum(1.0 / (1.0 + 10.0 ** ((elo[z["driver"]] - elo[d]) / 400.0))
                             for z in results if z["driver"] != d)
            denom = max(1, len(results)-1)
            elo[d] = current + 18.0 * ((actual_w / denom) - (expected_w / denom))
            ctor_elo[c] = 0.9 * ctor_elo[c] + 0.1 * (1500.0 + (25.0 - rr["position"]) * 20.0)
            finish_hist[d].append(rr["position"])
            dnf_hist[d].append(rr["dnf"])
            circuit_hist[d][circuit].append(rr["position"])
    return out


def metric(y, p):
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1-1e-6)
    return {
        "logloss": float(log_loss(y, np.c_[1-p, p], labels=[0, 1])),
        "brier": float(brier_score_loss(y, p)),
        "accuracy": float(accuracy_score(y, p >= 0.5)),
        "n": int(len(y)),
    }


def main() -> int:
    races = fetch_seasons()
    rows = build_pairwise_rows(races)
    race_keys = sorted({(r["season"], r["round"]) for r in rows})
    if len(race_keys) < 20:
        payload = {"sport": "f1", "status": "DEFERRED", "reason": "insufficient_free_jolpica_race_history", "races": len(race_keys)}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    holdout_start = max(1, int(len(race_keys) * 0.80))
    train_races = set(race_keys[:holdout_start])
    holdout_races = set(race_keys[holdout_start:])
    train_rows = [r for r in rows if (r["season"], r["round"]) in train_races]
    hold_rows = [r for r in rows if (r["season"], r["round"]) in holdout_races]

    X = np.asarray([r["x"] for r in train_rows], dtype=float)
    y = np.asarray([r["y"] for r in train_rows], dtype=int)
    folds = sorted(train_races)
    preds = {"logistic": [], "extra_trees": [], "hist_gb": []}
    targets = []
    for i in range(4, len(folds)):
        tr = set(folds[:i])
        te = set(folds[i:i+1])
        tr_rows = [r for r in train_rows if (r["season"], r["round"]) in tr]
        te_rows = [r for r in train_rows if (r["season"], r["round"]) in te]
        if len(tr_rows) < 200 or not te_rows:
            continue
        XT = np.asarray([r["x"] for r in tr_rows], float)
        yT = np.asarray([r["y"] for r in tr_rows], int)
        XE = np.asarray([r["x"] for r in te_rows], float)
        yE = np.asarray([r["y"] for r in te_rows], int)
        models = {
            "logistic": Pipeline([
                ("i", SimpleImputer(strategy="median", add_indicator=True)),
                ("s", StandardScaler()),
                ("m", LogisticRegression(C=0.25, max_iter=2000)),
            ]),
            "extra_trees": Pipeline([
                ("i", SimpleImputer(strategy="median", add_indicator=True)),
                ("m", ExtraTreesClassifier(n_estimators=300, min_samples_leaf=4, max_features="sqrt",
                                           class_weight="balanced", n_jobs=-1, random_state=42)),
            ]),
            "hist_gb": Pipeline([
                ("i", SimpleImputer(strategy="median", add_indicator=True)),
                ("m", HistGradientBoostingClassifier(max_iter=260, learning_rate=.04,
                                                     l2_regularization=1.5, max_leaf_nodes=15, random_state=43)),
            ]),
        }
        targets.extend(yE.tolist())
        for name, model in models.items():
            model.fit(XT, yT)
            preds[name].extend(model.predict_proba(XE)[:, 1].tolist())

    selection = {name: metric(np.asarray(targets), np.asarray(p)) for name, p in preds.items()}
    best = min(selection, key=lambda k: (selection[k]["logloss"], selection[k]["brier"]))
    final_model = {
        "logistic": Pipeline([("i", SimpleImputer(strategy="median", add_indicator=True)), ("s", StandardScaler()), ("m", LogisticRegression(C=0.25, max_iter=2000))]),
        "extra_trees": Pipeline([("i", SimpleImputer(strategy="median", add_indicator=True)), ("m", ExtraTreesClassifier(n_estimators=300, min_samples_leaf=4, max_features="sqrt", class_weight="balanced", n_jobs=-1, random_state=42))]),
        "hist_gb": Pipeline([("i", SimpleImputer(strategy="median", add_indicator=True)), ("m", HistGradientBoostingClassifier(max_iter=260, learning_rate=.04, l2_regularization=1.5, max_leaf_nodes=15, random_state=43))]),
    }[best]
    final_model.fit(X, y)
    XH = np.asarray([r["x"] for r in hold_rows], float)
    yH = np.asarray([r["y"] for r in hold_rows], int)
    hp = final_model.predict_proba(XH)[:, 1]
    holdout = metric(yH, hp) if len(np.unique(yH)) > 1 else {"status":"INSUFFICIENT_LABEL_VARIATION","n":len(yH)}

    payload = {
        "sport": "f1",
        "status": "RESEARCH_ONLY",
        "source": "Jolpica Ergast-compatible free API",
        "races": len(race_keys),
        "pairwise_rows": len(rows),
        "train_races": len(train_races),
        "frozen_holdout_races": len(holdout_races),
        "selection_oos": selection,
        "selected_model": best,
        "holdout_metrics": holdout,
        "prediction_target": "driver_A_finishes_ahead_of_driver_B",
        "pit_policy": "features derived only from races strictly before current race; current-race result never used as feature",
        "production_changed": False,
        "production_promotion_allowed": False,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
