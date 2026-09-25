from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
EXPERIENCE_DIR = RESULTS / "experience"
PREDICTIONS_DIR = EXPERIENCE_DIR / "predictions"
SUMMARY_OUT = RESULTS / "experience_summary.json"
PREDICTION_INDEX = EXPERIENCE_DIR / "prediction_ids.txt"
SETTLEMENTS_DIR = EXPERIENCE_DIR / "settlements"

SPORTS = (
    "valorant",
    "basketball",
    "volleyball",
    "tennis",
    "ufc",
    "rizin",
    "f1",
    "rugby",
    "boxing",
)
DB_PATHS = {
    "rugby": ROOT / "data/db/rugby_v45.sqlite",
    "boxing": ROOT / "data/db/boxing_v45.sqlite",
}

EPS = 1e-9


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(*parts: Any) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()[:32]


def _load_jsonl_dir(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for file in sorted(path.glob("*.jsonl")):
        with file.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"INVALID_EXPERIENCE_JSONL:{file}:{exc}") from exc
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def _append_settlements(rows: list[dict[str, Any]]) -> dict[str, int]:
    if not rows:
        return {"added": 0, "skipped_existing": 0}
    SETTLEMENTS_DIR.mkdir(parents=True, exist_ok=True)
    known = {str(r.get("prediction_id")) for r in _load_jsonl_dir(SETTLEMENTS_DIR) if r.get("prediction_id")}
    day = utc_now()[:10]
    out = SETTLEMENTS_DIR / f"{day}.jsonl"
    added = 0
    skipped = 0
    with out.open("a", encoding="utf-8") as fh:
        for row in rows:
            pid = str(row.get("prediction_id") or "")
            if not pid or pid in known:
                skipped += 1
                continue
            fh.write(_json(row) + "\n")
            known.add(pid)
            added += 1
    return {"added": added, "skipped_existing": skipped}


def _load_settlements() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in _load_jsonl_dir(SETTLEMENTS_DIR):
        pid = str(row.get("prediction_id") or "")
        if pid:
            out[pid] = row
    return out

def archive_predictions(results: list[dict[str, Any]], generated_at_utc: str | None = None) -> dict[str, int]:
    """
    Append normalized forward predictions to an append-only daily JSONL archive.
    Existing prediction IDs are never duplicated.
    """
    generated = generated_at_utc or utc_now()
    day = generated[:10]
    PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
    out = PREDICTIONS_DIR / f"{day}.jsonl"

    # The index is only an acceleration structure; the append-only archive is
    # the integrity source of truth. Re-scan archived records so an interruption
    # between JSONL append and index update cannot create a duplicate prediction.
    index_ids: set[str] = set()
    if PREDICTION_INDEX.exists():
        with PREDICTION_INDEX.open("r", encoding="utf-8") as fh:
            index_ids = {line.strip() for line in fh if line.strip()}

    archive_rows = _load_jsonl_dir(PREDICTIONS_DIR)
    archive_ids = {
        str(row.get("prediction_id"))
        for row in archive_rows
        if row.get("prediction_id")
    }
    existing_ids = index_ids | archive_ids

    # Repair any index entries that were lost after an earlier successful
    # JSONL append. This is safe because every repaired id already exists in the
    # durable archive; only new rows can still require the normal append path.
    missing_index_ids = sorted(archive_ids - index_ids)
    if missing_index_ids:
        EXPERIENCE_DIR.mkdir(parents=True, exist_ok=True)
        with PREDICTION_INDEX.open("a", encoding="utf-8") as fh:
            for pid in missing_index_ids:
                fh.write(pid + "\n")

    added = 0
    skipped = 0
    new_ids: list[str] = []
    with out.open("a", encoding="utf-8") as fh:
        for sport_result in results:
            sport = str(sport_result.get("sport") or "")
            if sport not in SPORTS:
                continue
            for pred in sport_result.get("predictions") or []:
                pid = str(pred.get("prediction_id") or "")
                if not pid:
                    # F1 multiclass predictions did not previously have a DB id.
                    pid = _sha(
                        "archive-v1",
                        sport,
                        pred.get("event_id"),
                        pred.get("prediction_cutoff_at_utc"),
                        pred.get("model_version"),
                        pred.get("generated_at_utc"),
                    )
                    pred = dict(pred)
                    pred["prediction_id"] = pid
                if pid in existing_ids:
                    skipped += 1
                    continue

                normalized = {
                    "archive_version": 1,
                    "prediction_id": pid,
                    "sport": sport,
                    "event_id": pred.get("event_id"),
                    "event_time_utc": pred.get("event_time_utc"),
                    "prediction_cutoff_at_utc": pred.get("prediction_cutoff_at_utc"),
                    "generated_at_utc": pred.get("generated_at_utc") or generated,
                    "side_a": pred.get("side_a"),
                    "side_b": pred.get("side_b"),
                    "probability_side_a": pred.get("probability_side_a"),
                    "probability_side_b": pred.get("probability_side_b"),
                    "drivers": pred.get("drivers"),
                    "strategy": pred.get("strategy"),
                    "router_status": pred.get("router_status"),
                    "model_version": pred.get("model_version"),
                    "feature_version": pred.get("feature_version"),
                    "confidence": pred.get("confidence"),
                    "action_state": pred.get("action_state"),
                    "models": pred.get("models"),
                    "ensemble_weights": pred.get("ensemble_weights"),
                    "situation": pred.get("situation"),
                }
                fh.write(_json(normalized) + "\n")
                existing_ids.add(pid)
                new_ids.append(pid)
                added += 1
    if new_ids:
        EXPERIENCE_DIR.mkdir(parents=True, exist_ok=True)
        with PREDICTION_INDEX.open("a", encoding="utf-8") as fh:
            for pid in new_ids:
                fh.write(pid + "\n")
    return {"added": added, "skipped_existing": skipped}



def archive_forward_prediction_db(
    c: sqlite3.Connection,
    sport: str,
    generated_at_utc: str | None = None,
) -> dict[str, int]:
    """Export persisted forward predictions from the current DB into the durable archive."""
    exists = c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='forward_prediction'"
    ).fetchone()
    if exists is None:
        return {"added": 0, "skipped_existing": 0}
    rows = c.execute(
        """SELECT prediction_id,event_id,prediction_cutoff_at_utc,generated_at_utc,
                  probability_side_a,probability_side_b,strategy,model_version,
                  feature_version,features_json,status
             FROM forward_prediction
            WHERE sport=?
            ORDER BY generated_at_utc,prediction_id""",
        (sport,),
    ).fetchall()
    preds = []
    for row in rows:
        try:
            features = json.loads(row[9]) if row[9] else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            features = {}
        preds.append({
            "prediction_id": row[0],
            "event_id": row[1],
            "prediction_cutoff_at_utc": row[2],
            "generated_at_utc": row[3] or generated_at_utc,
            "probability_side_a": row[4],
            "probability_side_b": row[5],
            "strategy": row[6],
            "model_version": row[7],
            "feature_version": row[8],
            "status": row[10],
            "situation": features.get("matchday_situation") if isinstance(features, dict) else None,
        })
    return archive_predictions([{"sport": sport, "predictions": preds}], generated_at_utc)

def _db_for_sport(sport: str) -> Path:
    return DB_PATHS.get(sport, ROOT / "data/db/sports_v45.sqlite")


def _connect_dbs() -> dict[str, sqlite3.Connection]:
    conns: dict[str, sqlite3.Connection] = {}
    for sport in SPORTS:
        path = _db_for_sport(sport)
        if not path.is_file() or path.stat().st_size <= 0:
            continue
        conns[sport] = sqlite3.connect(path)
    return conns


def _table_exists(c: sqlite3.Connection, name: str) -> bool:
    return c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def _binary_outcome(c: sqlite3.Connection, event_id: str) -> tuple[str | None, str | None, str | None]:
    if not _table_exists(c, "event_outcome"):
        return None, None, None
    row = c.execute(
        "SELECT outcome,outcome_status,source FROM event_outcome WHERE event_id=?",
        (event_id,),
    ).fetchone()
    if not row:
        return None, None, None
    return (
        str(row[0]).upper() if row[0] is not None else None,
        str(row[1]).upper() if row[1] is not None else None,
        str(row[2]) if row[2] is not None else None,
    )


def _f1_winner(c: sqlite3.Connection, event_id: str) -> tuple[str | None, str | None]:
    if not _table_exists(c, "match_stats"):
        return None, None
    row = c.execute(
        """SELECT participant_id,source
             FROM match_stats
            WHERE event_id=?
              AND sport='f1'
              AND stat_name='results.position'
              AND value_num=1
              AND participant_id IS NOT NULL
            ORDER BY participant_id
            LIMIT 1""",
        (event_id,),
    ).fetchone()
    if not row:
        return None, None
    return str(row[0]), str(row[1]) if row[1] is not None else None


def _bucket_probability(p: float) -> str:
    if p >= 0.90:
        return "0.90-1.00"
    if p >= 0.80:
        return "0.80-0.90"
    if p >= 0.70:
        return "0.70-0.80"
    if p >= 0.60:
        return "0.60-0.70"
    if p >= 0.55:
        return "0.55-0.60"
    if p >= 0.50:
        return "0.50-0.55"
    return "0.00-0.50"


def _experience_class(confidence: str | None, correct: bool, max_p: float) -> str:
    if correct:
        return "CORRECT_HIGH_CONF" if max_p >= 0.80 else "CORRECT_NONHIGH_CONF"
    if max_p >= 0.80:
        return "WRONG_OVERCONFIDENT"
    if confidence == "MEDIUM" or max_p >= 0.65:
        return "WRONG_MODERATE"
    return "WRONG_LOW_CONF"


def _case_profile(pred: dict[str, Any], max_p: float) -> dict[str, str]:
    situation = pred.get("situation") or {}
    quality = situation.get("quality") if isinstance(situation, dict) else {}
    quality = quality if isinstance(quality, dict) else {}
    conflict = quality.get("conflict_rate")
    evidence = quality.get("evidence_count")
    freshness = quality.get("freshness_score")

    if conflict is None:
        conflict_bucket = "unknown"
    else:
        try:
            v = float(conflict)
            conflict_bucket = "high" if v > 0.50 else "moderate" if v > 0.20 else "low"
        except Exception:
            conflict_bucket = "unknown"

    if evidence is None:
        evidence_bucket = "unknown"
    else:
        try:
            v = int(evidence)
            evidence_bucket = "0" if v <= 0 else "1-2" if v <= 2 else "3-5" if v <= 5 else "6+"
        except Exception:
            evidence_bucket = "unknown"

    if freshness is None:
        freshness_bucket = "unknown"
    else:
        try:
            v = float(freshness)
            freshness_bucket = "high" if v >= 0.75 else "medium" if v >= 0.50 else "low"
        except Exception:
            freshness_bucket = "unknown"

    return {
        "probability_bucket": _bucket_probability(max_p),
        "confidence": str(pred.get("confidence") or "UNKNOWN"),
        "action_state": str(pred.get("action_state") or "UNKNOWN"),
        "strategy": str(pred.get("strategy") or "UNKNOWN"),
        "conflict_bucket": conflict_bucket,
        "evidence_bucket": evidence_bucket,
        "freshness_bucket": freshness_bucket,
    }


def _validate_binary_probabilities(pred: dict[str, Any]) -> tuple[float, float]:
    """Fail closed on malformed binary prediction probabilities."""
    try:
        pa = float(pred.get("probability_side_a"))
        pb = float(pred.get("probability_side_b"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("INVALID_BINARY_PROBABILITIES:non_numeric") from exc
    if not (math.isfinite(pa) and math.isfinite(pb)):
        raise RuntimeError("INVALID_BINARY_PROBABILITIES:non_finite")
    if pa < -EPS or pa > 1.0 + EPS or pb < -EPS or pb > 1.0 + EPS:
        raise RuntimeError("INVALID_BINARY_PROBABILITIES:out_of_range")
    total = pa + pb
    if abs(total - 1.0) > 1e-6:
        raise RuntimeError("INVALID_BINARY_PROBABILITIES:sum_not_one")
    return pa, pb


def _score_binary(pred: dict[str, Any], outcome: str) -> dict[str, Any] | None:
    if outcome not in {"A", "B"}:
        return None
    pa, pb = _validate_binary_probabilities(pred)
    p = min(1.0 - EPS, max(EPS, pb if outcome == "B" else pa))
    y = 1.0 if outcome == "B" else 0.0
    max_p = max(pa, pb)
    correct = (pb >= 0.5) == (outcome == "B")
    logloss = -math.log(p)
    brier = (pb - y) ** 2
    return {
        "market": "winner_binary",
        "actual_outcome": outcome,
        "predicted_outcome": "B" if pb >= 0.5 else "A",
        "correct": bool(correct),
        "max_probability": float(max_p),
        "probability_true_outcome": float(p),
        "logloss": float(logloss),
        "brier": float(brier),
        "absolute_probability_error": float(abs(p - 1.0)),
        "experience_class": _experience_class(pred.get("confidence"), correct, max_p),
    }


def _score_f1(pred: dict[str, Any], winner_id: str | None) -> dict[str, Any] | None:
    if not winner_id:
        return None
    drivers = pred.get("drivers") or []
    if not isinstance(drivers, list):
        return None
    probs: dict[str, float] = {}
    for row in drivers:
        if not isinstance(row, dict) or not row.get("participant_id"):
            continue
        try:
            p = float(row.get("probability"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(p) or p < 0:
            continue
        probs[str(row["participant_id"])] = p
    if not probs:
        return None
    total = sum(probs.values())
    if total <= 0:
        return None
    probs = {k: v / total for k, v in probs.items()}
    true_p = min(1.0 - EPS, max(EPS, probs.get(winner_id, EPS)))
    max_pid, max_p = max(probs.items(), key=lambda kv: (kv[1], kv[0]))
    brier = sum((p - (1.0 if pid == winner_id else 0.0)) ** 2 for pid, p in probs.items())
    correct = max_pid == winner_id
    return {
        "market": "winner_multiclass",
        "actual_outcome_participant_id": winner_id,
        "predicted_outcome_participant_id": max_pid,
        "correct": bool(correct),
        "max_probability": float(max_p),
        "probability_true_outcome": float(true_p),
        "logloss": float(-math.log(true_p)),
        "brier": float(brier),
        "absolute_probability_error": float(abs(true_p - 1.0)),
        "experience_class": _experience_class(pred.get("confidence"), correct, max_p),
    }


def _summary(rows: list[dict[str, Any]], predictions_total: int, unresolved: Counter[str]) -> dict[str, Any]:
    scored = [r for r in rows if r.get("settlement_status") == "SCORED"]
    correct = [r for r in scored if r.get("correct") is True]

    def metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(items)
        if n == 0:
            return {"n": 0}
        acc = sum(bool(x.get("correct")) for x in items) / n
        return {
            "n": n,
            "accuracy": round(acc, 6),
            "logloss": round(sum(float(x["logloss"]) for x in items) / n, 6),
            "brier": round(sum(float(x["brier"]) for x in items) / n, 6),
        }

    def grouped(field: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in scored:
            groups[str(row.get(field) or "UNKNOWN")].append(row)
        for key, vals in sorted(groups.items()):
            out[key] = metrics(vals)
        return out

    sport_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scored:
        sport_groups[str(row.get("sport") or "UNKNOWN")].append(row)

    wrong = sorted(
        [r for r in scored if not r.get("correct")],
        key=lambda r: (
            -float(r.get("max_probability") or 0.0),
            str(r.get("settled_at_utc") or ""),
        ),
        reverse=False,
    )

    recent = sorted(scored, key=lambda r: str(r.get("settled_at_utc") or ""), reverse=True)

    return {
        "generated_at_utc": utc_now(),
        "prediction_archive_total": predictions_total,
        "resolved_scored_total": len(scored),
        "correct_total": len(correct),
        "unresolved_total": sum(unresolved.values()),
        "unresolved_reasons": dict(unresolved),
        "overall": metrics(scored),
        "by_sport": {sport: metrics(vals) for sport, vals in sorted(sport_groups.items())},
        "by_strategy": grouped("strategy"),
        "by_confidence": grouped("confidence"),
        "by_probability_bucket": grouped("probability_bucket"),
        "by_action_state": grouped("action_state"),
        "by_experience_class": grouped("experience_class"),
        "recent_100": metrics(recent[:100]),
        "recent_20": metrics(recent[:20]),
        "recent_wrong": wrong[:50],
        "repeated_error_patterns": _patterns(scored),
        "available_next_cycle_signals": _next_cycle_signals(scored),
    }


def _patterns(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scored:
        if row.get("correct"):
            continue
        key = "|".join(
            [
                str(row.get("sport") or "UNKNOWN"),
                str(row.get("strategy") or "UNKNOWN"),
                str(row.get("probability_bucket") or "UNKNOWN"),
                str(row.get("conflict_bucket") or "UNKNOWN"),
            ]
        )
        groups[key].append(row)

    patterns: list[dict[str, Any]] = []
    for key, vals in groups.items():
        if len(vals) < 3:
            continue
        sports, strategy, prob_bucket, conflict_bucket = key.split("|", 3)
        patterns.append(
            {
                "sport": sports,
                "strategy": strategy,
                "probability_bucket": prob_bucket,
                "conflict_bucket": conflict_bucket,
                "wrong_n": len(vals),
                "mean_max_probability": round(
                    sum(float(v.get("max_probability") or 0.0) for v in vals) / len(vals), 6
                ),
            }
        )
    patterns.sort(key=lambda x: (-x["wrong_n"], -x["mean_max_probability"], x["sport"]))
    return patterns[:50]


def _next_cycle_signals(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scored:
        key = "|".join(
            [
                str(row.get("sport") or "UNKNOWN"),
                str(row.get("strategy") or "UNKNOWN"),
                str(row.get("probability_bucket") or "UNKNOWN"),
            ]
        )
        by_key[key].append(row)
    out = []
    for key, vals in by_key.items():
        if len(vals) < 5:
            continue
        acc = sum(bool(v.get("correct")) for v in vals) / len(vals)
        if acc >= 0.60:
            continue
        sport, strategy, bucket = key.split("|", 2)
        out.append(
            {
                "sport": sport,
                "strategy": strategy,
                "probability_bucket": bucket,
                "n": len(vals),
                "accuracy": round(acc, 6),
                "reason": "historical_context_underperformance_requires_research_validation",
                "safe_use": "research_signal_only",
            }
        )
    out.sort(key=lambda x: (x["accuracy"], -x["n"], x["sport"]))
    return out[:30]


def score_archive() -> dict[str, Any]:
    predictions = _load_jsonl_dir(PREDICTIONS_DIR)
    conns = _connect_dbs()
    durable = _load_settlements()
    newly_settled: list[dict[str, Any]] = []
    unresolved: Counter[str] = Counter()
    scored_rows: list[dict[str, Any]] = []

    for pred in predictions:
        pid = str(pred.get("prediction_id") or "")
        if pid in durable:
            scored_rows.append(durable[pid])
            continue

        sport = str(pred.get("sport") or "")
        event_id = str(pred.get("event_id") or "")
        base = {
            "experience_version": 1,
            "prediction_id": pred.get("prediction_id"),
            "sport": sport,
            "event_id": event_id,
            "event_time_utc": pred.get("event_time_utc"),
            "prediction_cutoff_at_utc": pred.get("prediction_cutoff_at_utc"),
            "generated_at_utc": pred.get("generated_at_utc"),
            "strategy": pred.get("strategy"),
            "model_version": pred.get("model_version"),
            "feature_version": pred.get("feature_version"),
            "confidence": pred.get("confidence"),
            "action_state": pred.get("action_state"),
            "router_status": pred.get("router_status"),
            "side_a": pred.get("side_a"),
            "side_b": pred.get("side_b"),
        }

        c = conns.get(sport)
        if c is None:
            unresolved["NO_DATABASE"] += 1
            continue

        if sport == "f1":
            winner_id, source_out = _f1_winner(c, event_id)
            if not winner_id:
                unresolved["F1_WINNER_NOT_RESOLVED"] += 1
                continue
            result = _score_f1(pred, winner_id)
            if result is None:
                unresolved["F1_PREDICTION_SCHEMA_INVALID"] += 1
                continue
        else:
            outcome, status, source_out = _binary_outcome(c, event_id)
            if outcome is None:
                unresolved["OUTCOME_NOT_AVAILABLE"] += 1
                continue
            if status == "VERIFIED" and outcome not in {"A", "B", "VOID", "DRAW"}:
                raise RuntimeError(f"INVALID_ACTUAL_OUTCOME_LABEL:{outcome}")
            if status != "VERIFIED":
                unresolved[f"OUTCOME_STATUS_{status or 'UNKNOWN'}"] += 1
                continue
            if outcome in {"VOID", "DRAW"}:
                settled = dict(base)
                settled.update({
                    "settlement_status": "UNSCORABLE",
                    "unresolved_reason": f"UNSCORABLE_{outcome}",
                    "actual_outcome": outcome,
                    "settlement_source": source_out,
                    "settled_at_utc": utc_now(),
                })
                newly_settled.append(settled)
                scored_rows.append(settled)
                continue
            result = _score_binary(pred, outcome)

        if result is None:
            unresolved["PREDICTION_SCHEMA_INVALID"] += 1
            continue

        max_p = float(result.get("max_probability") or 0.0)
        prof = _case_profile(pred, max_p)
        settled = dict(base)
        settled.update(result)
        settled.update(prof)
        settled.update({
            "settlement_status": "SCORED",
            "settlement_source": source_out,
            "settled_at_utc": utc_now(),
            "case_id": _sha("experience-v1", pid, event_id, result.get("market")),
        })
        newly_settled.append(settled)
        scored_rows.append(settled)

    for c in conns.values():
        c.close()

    settlement_write = _append_settlements(newly_settled)
    # Build a durable view from the settlement ledger plus unresolved current archive.
    durable = _load_settlements()
    durable_rows = list(durable.values())
    unresolved_total = max(0, len(predictions) - len(durable_rows))
    summary = _summary(
        durable_rows,
        len(predictions),
        Counter({"NOT_YET_SETTLED": unresolved_total}),
    )
    summary["settlement_ledger_total"] = len(durable_rows)
    summary["new_settlements"] = settlement_write
    summary["predictions_waiting_for_result"] = unresolved_total
    summary["current_run_unresolved_reasons"] = dict(unresolved)
    EXPERIENCE_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_OUT.write_text(_json(summary) + "\n", encoding="utf-8")
    return summary

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Persist and score forward prediction experience.")
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args()

    # The archive is written by future_predictor. score-only keeps this module
    # safe to call independently on scheduled recovery jobs.
    result = score_archive()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
