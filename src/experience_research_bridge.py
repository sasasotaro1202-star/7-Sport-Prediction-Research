from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MEMORY_PATH = ROOT / "results" / "research" / "experience_learning.json"
OUT = ROOT / "results" / "research" / "experience_research_candidates.json"


def _parse_utc(value: Any) -> datetime:
    if value is None or str(value).strip() == "":
        raise RuntimeError("EXPERIENCE_BRIDGE_MISSING_KNOWLEDGE_TIME")
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _candidate_id(item: dict[str, Any]) -> str:
    key = "|".join(
        str(item.get(k) or "")
        for k in (
            "memory_key",
            "knowledge_available_at_utc",
            "source_settled_through_utc",
            "n",
        )
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def build(memory: dict[str, Any], generated_at_utc: str | None = None) -> dict[str, Any]:
    if not isinstance(memory, dict):
        raise RuntimeError("EXPERIENCE_BRIDGE_INVALID_MEMORY")
    if memory.get("pit_status") != "PASS":
        raise RuntimeError("EXPERIENCE_BRIDGE_MEMORY_NOT_PIT_SAFE")
    knowledge_time = _parse_utc(memory.get("knowledge_available_at_utc"))
    generated = _parse_utc(generated_at_utc or datetime.now(timezone.utc).isoformat())
    if knowledge_time > generated:
        raise RuntimeError("EXPERIENCE_BRIDGE_KNOWLEDGE_TIME_IN_FUTURE")

    candidates = []
    for item in memory.get("memory") or []:
        if not isinstance(item, dict):
            raise RuntimeError("EXPERIENCE_BRIDGE_INVALID_MEMORY_ROW")
        if str(item.get("recommendation") or "") != "EXPERIENCE_REVIEW":
            continue
        item_knowledge_time = _parse_utc(item.get("knowledge_available_at_utc"))
        if item_knowledge_time > generated:
            raise RuntimeError("EXPERIENCE_BRIDGE_ROW_KNOWLEDGE_TIME_IN_FUTURE")
        candidates.append({
            "candidate_id": _candidate_id(item),
            "status": "DISCOVERED_EXPERIENCE_HYPOTHESIS",
            "validation_mode": "PROSPECTIVE_ONLY",
            "promotion_allowed": False,
            "historical_oos_reuse_allowed": False,
            "pit_status": "PASS",
            "knowledge_available_at_utc": item_knowledge_time.isoformat(),
            "sport": item.get("sport"),
            "competition_profile_id": item.get("competition_profile_id"),
            "strategy": item.get("strategy"),
            "probability_bucket": item.get("probability_bucket"),
            "target_lead_minutes": item.get("target_lead_minutes"),
            "sample_n": int(item.get("n") or 0),
            "historical_accuracy": item.get("accuracy"),
            "accuracy_wilson_lower_bound": item.get("accuracy_wilson_lower_bound"),
            "high_confidence_n": int(item.get("high_confidence_n") or 0),
            "high_confidence_accuracy": item.get("high_confidence_accuracy"),
            "reason": item.get("reason"),
            "source_settled_through_utc": item.get("source_settled_through_utc"),
            "hypothesis": (
                "Observed repeated underperformance warrants a new challenger study "
                "for this exact segment; do not reuse future outcomes in historical OOS."
            ),
            "allowed_next_actions": [
                "prospective_shadow_evaluation",
                "chronological_oos_research_with_independent_data",
                "calibration_review",
                "abstention_or_fallback_study",
            ],
        })

    candidates.sort(key=lambda x: (-x["sample_n"], x["candidate_id"]))
    return {
        "version": "experience-research-bridge-v1",
        "generated_at_utc": generated.isoformat(),
        "knowledge_available_at_utc": knowledge_time.isoformat(),
        "pit_status": "PASS",
        "mode": "PROSPECTIVE_ONLY",
        "promotion_gate": False,
        "source_memory_version": memory.get("version"),
        "source_settled_through_utc": (memory.get("source") or {}).get("source_settled_through_utc"),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "safety": {
            "uses_outcomes_for_hypothesis_generation": True,
            "reuses_outcomes_in_historical_oos": False,
            "production_model_change": False,
            "automatic_promotion": False,
        },
    }


def build_from_file(memory_path: Path = MEMORY_PATH) -> dict[str, Any]:
    try:
        memory = json.loads(Path(memory_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "version": "experience-research-bridge-v1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "pit_status": "BLOCKED",
            "mode": "PROSPECTIVE_ONLY",
            "promotion_gate": False,
            "candidate_count": 0,
            "candidates": [],
            "reason": "experience_learning_artifact_missing",
        }
    except json.JSONDecodeError as exc:
        raise RuntimeError("EXPERIENCE_BRIDGE_INVALID_MEMORY_JSON") from exc
    return build(memory)


def main() -> int:
    artifact = build_from_file()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "READY" if artifact.get("pit_status") == "PASS" else "BLOCKED",
                "candidate_count": artifact.get("candidate_count", 0),
                "mode": artifact.get("mode"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if artifact.get("pit_status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
