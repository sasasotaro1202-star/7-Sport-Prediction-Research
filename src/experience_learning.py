from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SETTLEMENTS_DIR = ROOT / "results" / "experience" / "settlements"
POLICY_PATH = ROOT / "config" / "EXPERIENCE_LEARNING_POLICY.json"
OUT = ROOT / "results" / "research" / "experience_learning.json"

_MEMORY_CACHE: tuple[float, dict[str, Any]] | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_utc(value: Any) -> datetime:
    if value is None or str(value).strip() == "":
        raise RuntimeError("EXPERIENCE_LEARNING_INVALID_TIMESTAMP")
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _safe_float(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("EXPERIENCE_LEARNING_INVALID_NUMERIC") from exc
    if not math.isfinite(out):
        raise RuntimeError("EXPERIENCE_LEARNING_NONFINITE_NUMERIC")
    return out


def _profile_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("profile_id") or value.get("status") or "UNKNOWN")
    return str(value or "UNKNOWN")


def _group_key(
    sport: Any,
    competition_profile: Any,
    strategy: Any,
    probability_bucket: Any,
    target_lead_minutes: Any,
) -> str:
    return "|".join(
        (
            str(sport or "UNKNOWN"),
            _profile_id(competition_profile),
            str(strategy or "UNKNOWN"),
            str(probability_bucket or "UNKNOWN"),
            str(target_lead_minutes if target_lead_minutes is not None else "UNKNOWN"),
        )
    )


def _wilson_lower(successes: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    phat = successes / n
    denom = 1.0 + z * z / n
    centre = phat + z * z / (2.0 * n)
    spread = z * math.sqrt((phat * (1.0 - phat) / n) + (z * z / (4.0 * n * n)))
    return max(0.0, (centre - spread) / denom)


def _policy() -> dict[str, Any]:
    try:
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = {}
    if not isinstance(payload, dict):
        raise RuntimeError("EXPERIENCE_LEARNING_POLICY_INVALID")
    return payload


def _validate_row(row: dict[str, Any]) -> dict[str, Any] | None:
    if str(row.get("settlement_status") or "").upper() != "SCORED":
        return None
    prediction_cutoff = _parse_utc(row.get("prediction_cutoff_at_utc"))
    settled_at = _parse_utc(row.get("settled_at_utc"))
    if prediction_cutoff > settled_at:
        raise RuntimeError("EXPERIENCE_LEARNING_PIT_SETTLEMENT_BEFORE_CUTOFF")
    if row.get("correct") not in (True, False):
        raise RuntimeError("EXPERIENCE_LEARNING_INVALID_CORRECT_LABEL")
    max_probability = _safe_float(row.get("max_probability"))
    if not 0.0 <= max_probability <= 1.0:
        raise RuntimeError("EXPERIENCE_LEARNING_MAX_PROBABILITY_OUT_OF_RANGE")
    logloss = _safe_float(row.get("logloss"))
    brier = _safe_float(row.get("brier"))
    return {
        "prediction_id": str(row.get("prediction_id") or ""),
        "sport": str(row.get("sport") or "UNKNOWN"),
        "competition_profile": row.get("competition_profile"),
        "strategy": str(row.get("strategy") or "UNKNOWN"),
        "probability_bucket": str(row.get("probability_bucket") or "UNKNOWN"),
        "target_lead_minutes": row.get("target_lead_minutes", "UNKNOWN"),
        "correct": bool(row.get("correct")),
        "max_probability": max_probability,
        "logloss": logloss,
        "brier": brier,
        "settled_at_utc": settled_at.isoformat(),
        "prediction_cutoff_at_utc": prediction_cutoff.isoformat(),
    }


def load_settled_rows(settlements_dir: Path = SETTLEMENTS_DIR) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    path = Path(settlements_dir)
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
                    raise RuntimeError(f"EXPERIENCE_LEARNING_INVALID_JSONL:{file}") from exc
                if not isinstance(row, dict):
                    raise RuntimeError(f"EXPERIENCE_LEARNING_NON_OBJECT_ROW:{file}")
                normalized = _validate_row(row)
                if normalized is not None:
                    rows.append(normalized)
    rows.sort(key=lambda x: (x["settled_at_utc"], x["prediction_id"]))
    return rows


def build_memory(
    rows: list[dict[str, Any]],
    generated_at_utc: str | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or _policy()
    generated = _parse_utc(generated_at_utc or utc_now()).isoformat()
    minimums = policy.get("minimums") or {}
    thresholds = policy.get("review_thresholds") or {}
    min_rows = int(minimums.get("group_rows", 20))
    min_high_conf = int(minimums.get("high_confidence_rows", 15))
    accuracy_lb_threshold = float(thresholds.get("accuracy_wilson_lower_bound", 0.55))
    high_conf_lb_threshold = float(thresholds.get("high_confidence_accuracy_wilson_lower_bound", 0.60))

    validated_rows: list[dict[str, Any]] = []
    for row in rows:
        normalized = _validate_row(row)
        if normalized is not None:
            validated_rows.append(normalized)

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in validated_rows:
        groups[_group_key(
            row.get("sport"),
            row.get("competition_profile"),
            row.get("strategy"),
            row.get("probability_bucket"),
            row.get("target_lead_minutes"),
        )].append(row)

    memory: list[dict[str, Any]] = []
    review_count = 0
    for key, values in sorted(groups.items()):
        n = len(values)
        correct_n = sum(bool(x["correct"]) for x in values)
        accuracy = correct_n / n if n else 0.0
        accuracy_lb = _wilson_lower(correct_n, n)

        high = [x for x in values if x["max_probability"] >= 0.80]
        high_correct = sum(bool(x["correct"]) for x in high)
        high_accuracy = high_correct / len(high) if high else None
        high_lb = _wilson_lower(high_correct, len(high)) if high else None

        recommendation = "PASS"
        reason = "insufficient_or_non_degraded_historical_experience"
        if n >= min_rows and accuracy_lb <= accuracy_lb_threshold:
            recommendation = "EXPERIENCE_REVIEW"
            reason = "historical_accuracy_lower_bound_below_threshold"
        if len(high) >= min_high_conf and high_lb is not None and high_lb <= high_conf_lb_threshold:
            recommendation = "EXPERIENCE_REVIEW"
            reason = "high_confidence_accuracy_lower_bound_below_threshold"

        if recommendation != "PASS":
            review_count += 1

        sport, profile_id, strategy, probability_bucket, lead = key.split("|", 4)
        memory.append({
            "memory_key": key,
            "sport": sport,
            "competition_profile_id": profile_id,
            "strategy": strategy,
            "probability_bucket": probability_bucket,
            "target_lead_minutes": lead,
            "n": n,
            "accuracy": round(accuracy, 6),
            "accuracy_wilson_lower_bound": round(accuracy_lb, 6),
            "logloss": round(sum(x["logloss"] for x in values) / n, 6),
            "brier": round(sum(x["brier"] for x in values) / n, 6),
            "high_confidence_n": len(high),
            "high_confidence_accuracy": None if high_accuracy is None else round(high_accuracy, 6),
            "high_confidence_accuracy_wilson_lower_bound": None if high_lb is None else round(high_lb, 6),
            "recommendation": recommendation,
            "reason": reason,
            "knowledge_available_at_utc": generated,
            "source_settled_through_utc": max(x["settled_at_utc"] for x in values),
            "source_prediction_count": n,
        })

    return {
        "version": "experience-learning-v1",
        "generated_at_utc": generated,
        "knowledge_available_at_utc": generated,
        "pit_status": "PASS",
        "mode": "SHADOW_ONLY",
        "promotion_gate": False,
        "source": {
            "settlement_rows": len(validated_rows),
            "groups": len(memory),
            "review_groups": review_count,
            "source_settled_through_utc": max((x["settled_at_utc"] for x in rows), default=None),
        },
        "memory": memory,
        "policy": policy,
    }


def shadow_signal_from_memory(
    memory_artifact: dict[str, Any],
    prediction_time_utc: Any,
    sport: str,
    competition_profile_id: str,
    strategy: str,
    max_probability: float,
    target_lead_minutes: Any,
) -> dict[str, Any]:
    if not isinstance(memory_artifact, dict) or memory_artifact.get("pit_status") != "PASS":
        return {
            "status": "UNAVAILABLE",
            "recommendation": "PASS",
            "safe_action": "PASS",
            "reason": "experience_memory_unavailable_or_blocked",
        }
    prediction_time = _parse_utc(prediction_time_utc)
    p = _safe_float(max_probability)
    if not 0.0 <= p <= 1.0:
        raise RuntimeError("EXPERIENCE_LEARNING_PREDICTION_PROBABILITY_OUT_OF_RANGE")
    knowledge_available = _parse_utc(memory_artifact.get("knowledge_available_at_utc"))
    if knowledge_available > prediction_time:
        return {
            "status": "PIT_NOT_YET_AVAILABLE",
            "recommendation": "PASS",
            "safe_action": "PASS",
            "knowledge_available_at_utc": knowledge_available.isoformat(),
        }
    bucket = (
        "0.90-1.00" if p >= 0.90 else
        "0.80-0.90" if p >= 0.80 else
        "0.70-0.80" if p >= 0.70 else
        "0.60-0.70" if p >= 0.60 else
        "0.55-0.60" if p >= 0.55 else
        "0.50-0.55" if p >= 0.50 else
        "0.00-0.50"
    )
    lead = str(target_lead_minutes if target_lead_minutes is not None else "UNKNOWN")
    key = _group_key(sport, {"profile_id": competition_profile_id}, strategy, bucket, lead)
    for item in memory_artifact.get("memory") or []:
        if item.get("memory_key") != key:
            continue
        return {
            "status": "SHADOW",
            "recommendation": str(item.get("recommendation") or "PASS"),
            "safe_action": "PASS",
            "memory_key": key,
            "n": int(item.get("n") or 0),
            "historical_accuracy": item.get("accuracy"),
            "accuracy_wilson_lower_bound": item.get("accuracy_wilson_lower_bound"),
            "high_confidence_n": int(item.get("high_confidence_n") or 0),
            "high_confidence_accuracy": item.get("high_confidence_accuracy"),
            "high_confidence_accuracy_wilson_lower_bound": item.get("high_confidence_accuracy_wilson_lower_bound"),
            "reason": item.get("reason"),
            "knowledge_available_at_utc": item.get("knowledge_available_at_utc"),
            "source_settled_through_utc": item.get("source_settled_through_utc"),
        }
    return {
        "status": "SHADOW_NO_MATCH",
        "recommendation": "PASS",
        "safe_action": "PASS",
        "memory_key": key,
        "knowledge_available_at_utc": knowledge_available.isoformat(),
    }


def shadow_signal(
    prediction_time_utc: Any,
    sport: str,
    competition_profile_id: str,
    strategy: str,
    max_probability: float,
    target_lead_minutes: Any,
) -> dict[str, Any]:
    global _MEMORY_CACHE
    try:
        mtime = OUT.stat().st_mtime
    except FileNotFoundError:
        return {
            "status": "UNAVAILABLE",
            "recommendation": "PASS",
            "safe_action": "PASS",
            "reason": "experience_memory_artifact_missing",
        }
    if _MEMORY_CACHE is None or _MEMORY_CACHE[0] != mtime:
        try:
            payload = json.loads(OUT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _MEMORY_CACHE = None
            return {
                "status": "UNAVAILABLE",
                "recommendation": "PASS",
                "safe_action": "PASS",
                "reason": f"experience_memory_artifact_invalid:{type(exc).__name__}",
            }
        _MEMORY_CACHE = (mtime, payload)
    return shadow_signal_from_memory(
        _MEMORY_CACHE[1],
        prediction_time_utc,
        sport,
        competition_profile_id,
        strategy,
        max_probability,
        target_lead_minutes,
    )


def main() -> int:
    rows = load_settled_rows()
    artifact = build_memory(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "READY",
        "mode": artifact["mode"],
        "settlement_rows": artifact["source"]["settlement_rows"],
        "groups": artifact["source"]["groups"],
        "review_groups": artifact["source"]["review_groups"],
        "knowledge_available_at_utc": artifact["knowledge_available_at_utc"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
