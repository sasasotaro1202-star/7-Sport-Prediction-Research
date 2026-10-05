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
SHARED_DB_PATH = ROOT / "data/db/sports_v45.sqlite"
DB_PATHS = {
    **{sport: SHARED_DB_PATH for sport in SPORTS if sport not in {"rugby", "boxing"}},
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
        if not pid:
            raise RuntimeError("INVALID_SETTLEMENT_MISSING_PREDICTION_ID")
        previous = out.get(pid)
        if previous is None:
            out[pid] = row
            continue
        if previous != row:
            raise RuntimeError("CONFLICTING_SETTLEMENT_DUPLICATE")
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
                    "competition_id": pred.get("competition_id"),
                    "competition_profile": pred.get("competition_profile"),
                    "season": pred.get("season"),
                    "stage": pred.get("stage"),
                    "prediction_timing": pred.get("prediction_timing"),
                    "feature_pit_lead_minutes": pred.get("feature_pit_lead_minutes"),
                    "experience_shadow": pred.get("experience_shadow"),
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
            "competition_id": features.get("competition_id") if isinstance(features, dict) else None,
            "competition_profile": features.get("competition_profile") if isinstance(features, dict) else None,
            "season": features.get("season") if isinstance(features, dict) else None,
            "stage": features.get("stage") if isinstance(features, dict) else None,
            "prediction_timing": features.get("prediction_timing") if isinstance(features, dict) else None,
            "feature_pit_lead_minutes": features.get("feature_pit_lead_minutes") if isinstance(features, dict) else None,
            "experience_shadow": features.get("experience_shadow") if isinstance(features, dict) else None,
        })
    return archive_predictions([{"sport": sport, "predictions": preds}], generated_at_utc)



def _artifact_jsonl_files(artifact_root: Path, leaf: str) -> list[Path]:
    root = Path(artifact_root)
    if not root.exists():
        return []
    return sorted(
        p
        for p in root.rglob("*.jsonl")
        if p.parent.name == leaf and p.parent.parent.name == "experience"
    )


def _merge_append_only_jsonl(
    target_dir: Path,
    incoming_files: list[Path],
    key: str,
    date_field: str,
) -> dict[str, int | bool]:
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    existing_rows = _load_jsonl_dir(target)
    by_id: dict[str, dict[str, Any]] = {}
    for row in existing_rows:
        value = str(row.get(key) or "")
        if not value:
            raise RuntimeError(f"EXPERIENCE_ARCHIVE_EXISTING_MISSING_{key.upper()}")
        previous = by_id.get(value)
        if previous is not None and previous != row:
            raise RuntimeError(f"EXPERIENCE_ARCHIVE_EXISTING_CONFLICT:{key}:{value}")
        by_id[value] = row

    incoming_ids: set[str] = set()
    incoming_days: set[str] = set()
    added = 0
    for path in incoming_files:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"EXPERIENCE_ARTIFACT_INVALID_JSONL:{path}") from exc
            if not isinstance(row, dict):
                raise RuntimeError(f"EXPERIENCE_ARTIFACT_INVALID_ROW:{path}")
            value = str(row.get(key) or "")
            if not value:
                raise RuntimeError(f"EXPERIENCE_ARTIFACT_MISSING_{key.upper()}:{path}")
            day_raw = str(row.get(date_field) or "")[:10]
            try:
                datetime.fromisoformat(day_raw).date()
            except ValueError as exc:
                raise RuntimeError(f"EXPERIENCE_ARTIFACT_INVALID_DATE:{date_field}:{value}") from exc
            incoming_days.add(day_raw)
            incoming_ids.add(value)
            previous = by_id.get(value)
            if previous is None:
                by_id[value] = row
                added += 1
            elif previous != row:
                raise RuntimeError(f"EXPERIENCE_ARTIFACT_CONFLICT:{key}:{value}")

    changed = False
    for day in sorted(incoming_days):
        rows = [
            row for row in by_id.values()
            if str(row.get(date_field) or "")[:10] == day
        ]
        rows.sort(
            key=lambda row: (
                str(row.get(date_field) or ""),
                str(row.get("event_id") or ""),
                str(row.get("prediction_cutoff_at_utc") or ""),
                str(row.get(key) or ""),
            )
        )
        content = "".join(_json(row) + "\n" for row in rows)
        path = target / f"{day}.jsonl"
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        if old != content:
            path.write_text(content, encoding="utf-8")
            changed = True

    return {
        "changed": changed,
        "added": added,
        "incoming_ids": len(incoming_ids),
    }


def merge_experience_artifacts(artifact_root: Path) -> dict[str, Any]:
    root = Path(artifact_root)
    prediction_files = _artifact_jsonl_files(root, "predictions")
    settlement_files = _artifact_jsonl_files(root, "settlements")

    prediction_merge = _merge_append_only_jsonl(
        PREDICTIONS_DIR,
        prediction_files,
        "prediction_id",
        "generated_at_utc",
    )
    settlement_merge = _merge_append_only_jsonl(
        SETTLEMENTS_DIR,
        settlement_files,
        "prediction_id",
        "settled_at_utc",
    )

    all_prediction_ids = sorted(
        str(row.get("prediction_id") or "")
        for row in _load_jsonl_dir(PREDICTIONS_DIR)
        if row.get("prediction_id")
    )
    if len(all_prediction_ids) != len(set(all_prediction_ids)):
        raise RuntimeError("EXPERIENCE_ARCHIVE_DUPLICATE_PREDICTION_ID")
    index_content = "".join(pid + "\n" for pid in all_prediction_ids)
    old_index = PREDICTION_INDEX.read_text(encoding="utf-8") if PREDICTION_INDEX.exists() else ""
    PREDICTION_INDEX.parent.mkdir(parents=True, exist_ok=True)
    PREDICTION_INDEX.write_text(index_content, encoding="utf-8")
    index_changed = old_index != index_content

    settled_rows = load_settled_rows(SETTLEMENTS_DIR)
    memory, memory_changed = persist_memory(settled_rows)
    from src.experience_research_bridge import build, persist_candidates
    candidates = json.loads(
        (ROOT / "results" / "research" / "experience_learning.json").read_text(
            encoding="utf-8"
        )
    )
    candidate_artifact = build(candidates)
    _, candidates_changed = persist_candidates(candidate_artifact)

    return {
        "prediction_merge": prediction_merge,
        "settlement_merge": settlement_merge,
        "prediction_index_changed": index_changed,
        "memory_changed": memory_changed,
        "candidates_changed": candidates_changed,
        "prediction_count": len(_load_jsonl_dir(PREDICTIONS_DIR)),
        "settlement_count": len(settled_rows),
        "memory_groups": int(memory.get("source", {}).get("groups") or 0),
    }


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


def _validate_f1_multiclass_probabilities(pred: dict[str, Any]) -> dict[str, float]:
    """Fail closed on malformed F1 multiclass probability vectors."""
    drivers = pred.get("drivers")
    if not isinstance(drivers, list) or not drivers:
        raise RuntimeError("INVALID_F1_PROBABILITIES:missing_or_not_list")

    probs: dict[str, float] = {}
    seen: set[str] = set()
    for row in drivers:
        if not isinstance(row, dict):
            raise RuntimeError("INVALID_F1_PROBABILITIES:invalid_driver_row")
        participant_id = row.get("participant_id")
        if not participant_id:
            raise RuntimeError("INVALID_F1_PROBABILITIES:missing_participant_id")
        participant_id = str(participant_id)
        if participant_id in seen:
            raise RuntimeError("INVALID_F1_PROBABILITIES:duplicate_participant_id")
        seen.add(participant_id)
        try:
            p = float(row.get("probability"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("INVALID_F1_PROBABILITIES:non_numeric") from exc
        if not math.isfinite(p):
            raise RuntimeError("INVALID_F1_PROBABILITIES:non_finite")
        if p < 0.0 or p > 1.0:
            raise RuntimeError("INVALID_F1_PROBABILITIES:out_of_range")
        probs[participant_id] = p

    total = sum(probs.values())
    if not math.isfinite(total) or total <= 0.0:
        raise RuntimeError("INVALID_F1_PROBABILITIES:invalid_sum")
    if abs(total - 1.0) > 1e-6:
        raise RuntimeError("INVALID_F1_PROBABILITIES:sum_not_one")
    return probs


def _score_f1(pred: dict[str, Any], winner_id: str | None) -> dict[str, Any] | None:
    if not winner_id:
        return None
    probs = _validate_f1_multiclass_probabilities(pred)
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


def _parse_utc(value: Any) -> datetime | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_event_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """
    Reduce scored prediction snapshots to one deterministic experience sample per
    event/market. Raw snapshots remain in the settlement ledger; this view is
    used for canonical performance metrics so timing-shadow/revision snapshots
    cannot inflate the event sample count.
    """
    groups: dict[tuple[str, str, str], list[tuple[datetime, datetime, str, dict[str, Any]]]] = defaultdict(list)
    excluded_invalid_timing = 0
    for row in rows:
        sport = str(row.get("sport") or "")
        event_id = str(row.get("event_id") or "")
        market = str(row.get("market") or "winner_binary")
        event_time = _parse_utc(row.get("event_time_utc"))
        cutoff = _parse_utc(row.get("prediction_cutoff_at_utc"))
        generated = _parse_utc(row.get("generated_at_utc"))
        if not sport or not event_id or event_time is None or cutoff is None:
            excluded_invalid_timing += 1
            continue
        if cutoff > event_time or (generated is not None and generated > event_time):
            excluded_invalid_timing += 1
            continue
        groups[(sport, event_id, market)].append(
            (cutoff, generated or cutoff, str(row.get("prediction_id") or ""), row)
        )

    selected: list[dict[str, Any]] = []
    for candidates in groups.values():
        _, _, _, row = max(candidates, key=lambda item: (item[0], item[1], item[2]))
        selected.append(row)

    selected.sort(
        key=lambda row: (
            str(row.get("sport") or ""),
            str(row.get("event_id") or ""),
            str(row.get("market") or ""),
            str(row.get("prediction_cutoff_at_utc") or ""),
            str(row.get("prediction_id") or ""),
        )
    )
    return selected, {
        "canonical_event_markets": len(selected),
        "excluded_invalid_timing": excluded_invalid_timing,
        "snapshot_rows": len(rows),
    }


def _summary(rows: list[dict[str, Any]], predictions_total: int, unresolved: Counter[str]) -> dict[str, Any]:
    snapshot_scored = [r for r in rows if r.get("settlement_status") == "SCORED"]
    canonical_scored, canonical_stats = _canonical_event_rows(snapshot_scored)
    correct = [r for r in canonical_scored if r.get("correct") is True]
    snapshot_correct = [r for r in snapshot_scored if r.get("correct") is True]

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

    def grouped(field: str, source: list[dict[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in source:
            value = row.get(field)
            if isinstance(value, dict):
                key = str(value.get("profile_id") or value.get("status") or "UNKNOWN")
            else:
                key = str(value or "UNKNOWN")
            groups[key].append(row)
        for key, vals in sorted(groups.items()):
            out[key] = metrics(vals)
        return out

    def grouped_target_lead(source: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            key: metrics(vals)
            for key, vals in sorted(
                _group_rows(source, "target_lead_minutes").items(),
                key=lambda item: item[0],
            )
        }

    sport_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    canonical_sport_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in snapshot_scored:
        sport_groups[str(row.get("sport") or "UNKNOWN")].append(row)
    for row in canonical_scored:
        canonical_sport_groups[str(row.get("sport") or "UNKNOWN")].append(row)

    wrong = sorted(
        [r for r in snapshot_scored if not r.get("correct")],
        key=lambda r: (
            -float(r.get("max_probability") or 0.0),
            str(r.get("settled_at_utc") or ""),
        ),
        reverse=False,
    )
    recent = sorted(snapshot_scored, key=lambda r: str(r.get("settled_at_utc") or ""), reverse=True)
    recent_canonical = sorted(
        canonical_scored,
        key=lambda r: str(r.get("settled_at_utc") or ""),
        reverse=True,
    )

    return {
        "generated_at_utc": utc_now(),
        "prediction_archive_total": predictions_total,
        "resolved_scored_total": len(snapshot_scored),
        "correct_total": len(correct),
        "snapshot_correct_total": len(snapshot_correct),
        "unresolved_total": sum(unresolved.values()),
        "overall": metrics(canonical_scored),
        "snapshot_overall": metrics(snapshot_scored),
        "canonical_event_sample_total": canonical_stats["canonical_event_markets"],
        "canonical_excluded_invalid_timing": canonical_stats["excluded_invalid_timing"],
        "canonical_selection_policy": "latest_valid_pre_event_prediction_per_event_market_by_cutoff_then_generation_then_prediction_id",
        "by_sport": {sport: metrics(vals) for sport, vals in sorted(canonical_sport_groups.items())},
        "snapshot_by_sport": {sport: metrics(vals) for sport, vals in sorted(sport_groups.items())},
        "by_strategy": grouped("strategy", snapshot_scored),
        "by_competition_profile": grouped("competition_profile", snapshot_scored),
        "by_prediction_timing_status": grouped("prediction_timing_status", snapshot_scored),
        "by_target_lead_minutes": grouped_target_lead(snapshot_scored),
        "canonical_by_competition_profile": grouped("competition_profile", canonical_scored),
        "canonical_by_prediction_timing_status": grouped("prediction_timing_status", canonical_scored),
        "canonical_by_target_lead_minutes": grouped_target_lead(canonical_scored),
        "by_confidence": grouped("confidence", snapshot_scored),
        "by_probability_bucket": grouped("probability_bucket", snapshot_scored),
        "by_action_state": grouped("action_state", snapshot_scored),
        "by_experience_class": grouped("experience_class", snapshot_scored),
        "by_experience_shadow": grouped("experience_shadow", snapshot_scored),
        "recent_100": metrics(recent[:100]),
        "recent_20": metrics(recent[:20]),
        "recent_canonical_100": metrics(recent_canonical[:100]),
        "recent_wrong": wrong[:50],
        "repeated_error_patterns": _patterns(snapshot_scored),
        "available_next_cycle_signals": _next_cycle_signals(snapshot_scored),
    }


def _group_rows(rows: list[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row.get(field)
        if isinstance(value, dict):
            key = str(value.get("status") or value.get("profile_id") or "UNKNOWN")
        else:
            key = str(value or "UNKNOWN")
        groups[key].append(row)
    return groups


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
            "competition_id": pred.get("competition_id"),
            "competition_profile": pred.get("competition_profile"),
            "season": pred.get("season"),
            "stage": pred.get("stage"),
            "prediction_timing": pred.get("prediction_timing"),
            "feature_pit_lead_minutes": pred.get("feature_pit_lead_minutes"),
            "experience_shadow": pred.get("experience_shadow"),
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
        timing = pred.get("prediction_timing")
        timing_status = timing.get("status") if isinstance(timing, dict) else None
        settled.update({
            "experience_shadow": pred.get("experience_shadow"),
            "prediction_timing_status": timing_status or "UNKNOWN",
            "target_lead_minutes": (
                int(timing.get("target_lead_minutes"))
                if isinstance(timing, dict) and timing.get("target_lead_minutes") is not None
                else "UNKNOWN"
            ),
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
    parser.add_argument(
        "--archive-db-sport",
        choices=sorted(DB_PATHS),
        help="Rebuild the append-only experience prediction archive from the persistent forward_prediction DB for one sport before scoring.",
    )
    parser.add_argument(
        "--merge-artifacts",
        help="Merge per-sport GitHub Actions experience artifacts into the durable single-writer archive.",
    )
    args = parser.parse_args()

    if args.merge_artifacts:
        result = merge_experience_artifacts(Path(args.merge_artifacts))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    archive_result = None
    if args.archive_db_sport:
        db_path = _db_for_sport(args.archive_db_sport)
        if not db_path.is_file() or db_path.stat().st_size <= 0:
            raise RuntimeError(f"EXPERIENCE_DB_MISSING:{args.archive_db_sport}")
        con = sqlite3.connect(db_path)
        try:
            archive_result = archive_forward_prediction_db(
                con,
                args.archive_db_sport,
                utc_now(),
            )
        finally:
            con.close()

    # The archive is written by future_predictor and can also be reconstructed
    # from the persistent forward_prediction DB. score-only remains safe to call
    # independently on scheduled recovery jobs.
    result = score_archive()
    result["archive_db_sport"] = args.archive_db_sport
    result["archive_db_sync"] = archive_result
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
