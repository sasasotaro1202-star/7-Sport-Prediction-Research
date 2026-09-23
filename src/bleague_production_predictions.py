from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import joblib
import numpy as np
import requests
from bs4 import BeautifulSoup

from src import research_cycle_v4 as base
from src.seven_sport_production import add_snapshot, upsert_ep, upsert_event, upsert_participant

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
MODEL = ROOT / "models/research/basketball_current.joblib"
OUT = ROOT / "results/bleague_production_predictions.json"
SOURCE_URL = "https://bleague-insider.com/season/2026-27/"
SOURCE = "bleague_insider_schedule_discovery"
TZ_JST = timezone(timedelta(hours=9))
LOOKAHEAD_DAYS = 10
TIMEOUT = 20
HEADERS = {"User-Agent": "SevenSportResearchEngine/4.6 BLeagueProduction/1.0"}

def now_jst():
    return datetime.now(timezone.utc).astimezone(TZ_JST)

def parse_dt(text, now):
    m = re.search(r"(\d{1,2})/(\d{1,2})", text)
    if not m:
        return None
    month, day = map(int, m.groups())
    tm = re.search(r"(\d{1,2}):(\d{2})", text)
    hour, minute = (int(tm.group(1)), int(tm.group(2))) if tm else (12, 0)
    try:
        return datetime(now.year, month, day, hour, minute, tzinfo=TZ_JST)
    except ValueError:
        return None

def page_heading(soup):
    h = soup.find("h1")
    raw = h.get_text(" ", strip=True) if h else (soup.title.get_text(" ", strip=True) if soup.title else "")
    return re.split(r"\s+2026-27", re.sub(r"\s+", " ", raw), maxsplit=1)[0].strip()

def discover_clubs():
    r = requests.get(SOURCE_URL, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    urls = set()
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if re.search(r"/season/2026-27/[^/]+/?$", href):
            urls.add(urljoin(SOURCE_URL, href))
    return sorted(urls)

def parse_club(url, now):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    home = page_heading(soup)
    page_text = soup.get_text(" ", strip=True)
    tier = "B.LEAGUE PREMIER" if "B.LEAGUE PREMIER" in page_text else "B.LEAGUE ONE"
    rows = []
    for tr in soup.select("tr"):
        cells = [x.get_text(" ", strip=True) for x in tr.find_all(["th", "td"])]
        joined = " | ".join(cells)
        if not re.search(r"\b\d{1,2}/\d{1,2}\b", joined):
            continue
        m = re.search(r"\bvs\s+([^|]+)", joined, re.I)
        if not m:
            continue
        dt = parse_dt(joined, now)
        if dt is None:
            continue
        rows.append({
            "event_time_jst": dt.isoformat(),
            "home": home,
            "away": re.sub(r"\s+", " ", m.group(1)).strip(),
            "tier": tier,
            "source_url": url,
            "schedule_time_known": bool(re.search(r"\b\d{1,2}:\d{2}\b", joined)),
        })
    return rows

def discover_schedule(now):
    end = now + timedelta(days=LOOKAHEAD_DAYS)
    rows, errors = [], []
    with ThreadPoolExecutor(max_workers=8) as ex:
        fs = {ex.submit(parse_club, u, now): u for u in discover_clubs()}
        for fut in as_completed(fs):
            try:
                rows.extend(fut.result())
            except Exception as exc:
                errors.append({"url": fs[fut], "error": type(exc).__name__})
    uniq = {}
    for x in rows:
        dt = datetime.fromisoformat(x["event_time_jst"])
        if now <= dt <= end:
            uniq[(x["event_time_jst"], x["home"], x["away"])] = x
    return sorted(uniq.values(), key=lambda x: (x["event_time_jst"], x["home"], x["away"])), errors

def inject(db, games, observed_at):
    by_id = {}
    for g in games:
        et = datetime.fromisoformat(g["event_time_jst"]).astimezone(timezone.utc).isoformat()
        eid = upsert_event(db, "basketball", f"{g['home']} vs {g['away']}", et, SOURCE, g["source_url"], "SCHEDULED",
                           competition=g["tier"], season="2026-27")
        pa = upsert_participant(db, "basketball", g["home"], "team")
        pb = upsert_participant(db, "basketball", g["away"], "team")
        upsert_ep(db, eid, pa, pa, "A", "match", SOURCE, g["source_url"])
        upsert_ep(db, eid, pb, pb, "B", "match", SOURCE, g["source_url"])
        payload_hash = hashlib.sha256(json.dumps(g, sort_keys=True).encode()).hexdigest()
        add_snapshot(db, "basketball", SOURCE, g["source_url"], observed_at, et, payload_hash, "EXACT",
                     source_available_at_utc=observed_at,
                     provenance={"purpose":"future_schedule_discovery","future_event":True,"source":"public_schedule"})
        by_id[eid] = g
    db.commit()
    return by_id

def apply_calibration(p, calibrator, method):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1-1e-6)
    if calibrator is None or method == "none":
        return p
    if method == "sigmoid":
        z = np.log(p/(1-p)).reshape(-1,1)
        return np.clip(calibrator.predict_proba(z)[:,1], 1e-6, 1-1e-6)
    if method == "beta":
        z = np.column_stack([np.log(p), np.log(1-p)])
        return np.clip(calibrator.predict_proba(z)[:,1], 1e-6, 1-1e-6)
    if method == "isotonic":
        return np.clip(calibrator.predict(p), 1e-6, 1-1e-6)
    raise RuntimeError(f"unsupported calibration method: {method}")

def predict(artifact, feature_rows, games):
    if artifact.get("quality_status") not in ("ACCEPTED_LOCKED_HOLDOUT","ACCEPTED_AFTER_LOCKED_HOLDOUT"):
        raise RuntimeError("accepted production artifact required")
    feature_names = list(artifact.get("features") or [])
    models = list(artifact.get("models") or [])
    names = list(artifact.get("model_names") or [])
    weights = artifact.get("ensemble_weights") or {}
    if not feature_names or len(models) != len(names) or not models:
        raise RuntimeError("production artifact schema invalid")
    router_status = str(artifact.get("dynamic_router_status") or "FALLBACK_FIXED_ENSEMBLE")
    cal = artifact.get("probability_calibrator")
    cal_method = str((artifact.get("probability_calibration") or {}).get("method") or "none")
    out = []
    for eid, game in games.items():
        f = feature_rows.get(eid)
        cold = f is None
        if cold:
            f = {k: np.nan for k in feature_names}
            if "competition_is_bleague" in f:
                f["competition_is_bleague"] = 1.0
            for k in ("A__elo","B__elo","A__elo_comp","B__elo_comp","A__elo_fast","B__elo_fast","A__elo_slow","B__elo_slow"):
                if k in f: f[k] = 1500.0
            for k in ("A__history_n","B__history_n","A__games_last_7d","B__games_last_7d","A__games_last_14d","B__games_last_14d","A__games_last_30d","B__games_last_30d"):
                if k in f: f[k] = 0.0
        x = np.asarray([[f.get(k, np.nan) for k in feature_names]], dtype=float)
        preds = [float(np.clip(m.predict_proba(x)[0,1], 1e-6, 1-1e-6)) for m in models]
        ws = [float(weights.get(n, 1.0/len(names))) for n in names]
        raw = np.asarray([sum(p*w for p,w in zip(preds,ws))/max(sum(ws),1e-12)])
        p = float(apply_calibration(raw, cal, cal_method)[0])
        out.append({
            "event_id": eid,
            "date_jst": game["event_time_jst"][:10],
            "time_jst": game["event_time_jst"][11:16],
            "tier": game["tier"],
            "home": game["home"],
            "away": game["away"],
            "probability_home_pct": round((1-p)*100, 2),
            "probability_away_pct": round(p*100, 2),
            "predicted_winner": game["away"] if p >= 0.5 else game["home"],
            "strategy": str(artifact.get("ensemble_strategy") or "fixed_weighted_ensemble"),
            "models": names,
            "ensemble_weights": weights,
            "model_version": artifact.get("model_version"),
            "feature_version": artifact.get("feature_version"),
            "cold_start": cold,
            "schedule_time_known": game["schedule_time_known"],
            "router_status": router_status,
        })
    return out

def main():
    now = now_jst()
    observed_at = datetime.now(timezone.utc).isoformat()
    games, schedule_errors = discover_schedule(now)
    if not games:
        raise RuntimeError("no upcoming B.LEAGUE games discovered")
    artifact = joblib.load(MODEL)
    tmp = ROOT / "data/db/.bleague_prediction_tmp.sqlite"
    if tmp.exists(): tmp.unlink()
    shutil.copy2(DB, tmp)
    con = sqlite3.connect(tmp)
    try:
        em = inject(con, games, observed_at)
        rows, _ = base.build(con, "basketball", include_unlabeled=True)
        feature_rows = {eid: f for eid, _t, _label, f in rows if eid in em}
        preds = predict(artifact, feature_rows, em)
    finally:
        con.close()
        tmp.unlink(missing_ok=True)
    report = {
        "generated_at_utc": observed_at,
        "as_of_jst": now.isoformat(),
        "through_jst": (now + timedelta(days=LOOKAHEAD_DAYS)).isoformat(),
        "source": SOURCE_URL,
        "source_policy": "schedule discovery only; inference uses the accepted Basketball production artifact",
        "quality_status": artifact.get("quality_status"),
        "model_version": artifact.get("model_version"),
        "feature_version": artifact.get("feature_version"),
        "count": len(preds),
        "schedule_errors": schedule_errors,
        "predictions": preds,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
