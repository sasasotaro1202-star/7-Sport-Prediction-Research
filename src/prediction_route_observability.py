from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
OUT = ROOT / "results/research/production_route_observability.json"
ACTIVE_SPORTS = ("valorant", "basketball", "volleyball", "ufc", "rizin")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size <= 0:
        return {"status": "MISSING", "routes": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "INVALID", "routes": {}}
    return value if isinstance(value, dict) else {"status": "INVALID", "routes": {}}


def _route_summary(path: Path) -> dict[str, Any]:
    value = _load_json(path)
    routes = value.get("routes") if isinstance(value.get("routes"), dict) else {}
    accepted = sorted(
        str(key) for key, route in routes.items()
        if isinstance(route, dict) and str(route.get("quality_status") or "") == "ACCEPTED_LOCKED_HOLDOUT"
    )
    return {
        "status": str(value.get("status") or "MISSING"),
        "route_count": len(routes),
        "accepted_route_count": len(accepted),
        "accepted_routes": accepted,
    }


def _utc(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _features(raw: Any) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    try:
        value = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise RuntimeError("ROUTE_OBSERVABILITY_INVALID_FEATURES_JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("ROUTE_OBSERVABILITY_FEATURES_NOT_OBJECT")
    return value


def _group_counter(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        value = row.get(key)
        counter[str(value if value not in (None, "") else "UNKNOWN")] += 1
    return dict(sorted(counter.items()))


def build_report(db_path: Path = DB, now: datetime | None = None) -> dict[str, Any]:
    db_path = Path(db_path).resolve()
    if not db_path.is_file() or db_path.stat().st_size <= 0:
        raise FileNotFoundError(db_path)

    generated_at = now or datetime.now(timezone.utc)
    con = sqlite3.connect(db_path)
    try:
        tables = {
            str(row[0])
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "forward_prediction" not in tables:
            raise RuntimeError("ROUTE_OBSERVABILITY_FORWARD_PREDICTION_TABLE_MISSING")

        columns = {
            str(row[1])
            for row in con.execute("PRAGMA table_info(forward_prediction)")
        }
        required = {
            "prediction_id",
            "event_id",
            "sport",
            "prediction_cutoff_at_utc",
            "generated_at_utc",
            "strategy",
            "features_json",
            "status",
        }
        missing = sorted(required - columns)
        if missing:
            raise RuntimeError("ROUTE_OBSERVABILITY_SCHEMA_MISSING:" + ",".join(missing))

        raw_rows = con.execute(
            """
            SELECT prediction_id,event_id,sport,prediction_cutoff_at_utc,
                   generated_at_utc,strategy,features_json,status
              FROM forward_prediction
             WHERE sport IN (?,?,?,?,?)
             ORDER BY generated_at_utc,prediction_id
            """,
            ACTIVE_SPORTS,
        ).fetchall()

        rows: list[dict[str, Any]] = []
        malformed = 0
        for pid, event_id, sport, cutoff, generated, strategy, raw_features, status in raw_rows:
            try:
                features = _features(raw_features)
            except RuntimeError:
                malformed += 1
                continue
            routing = features.get("routing") if isinstance(features.get("routing"), dict) else {}
            timing = features.get("prediction_timing") if isinstance(features.get("prediction_timing"), dict) else {}
            profile = features.get("competition_profile") if isinstance(features.get("competition_profile"), dict) else {}
            generated_dt = _utc(generated)
            cutoff_dt = _utc(cutoff)
            late = (
                generated_dt is not None
                and cutoff_dt is not None
                and generated_dt > cutoff_dt
            )
            rows.append(
                {
                    "prediction_id": str(pid),
                    "event_id": str(event_id),
                    "sport": str(sport),
                    "strategy": str(strategy or "UNKNOWN"),
                    "status": str(status or "UNKNOWN"),
                    "router_status": str(routing.get("status") or "UNKNOWN"),
                    "competition_specific": bool(routing.get("competition_specific", False)),
                    "competition_profile": str(
                        profile.get("profile_id")
                        or features.get("competition_profile")
                        or "UNKNOWN"
                    ),
                    "timing_selection_status": str(
                        features.get("timing_selection_status")
                        or timing.get("selection_status")
                        or "UNKNOWN"
                    ),
                    "target_lead_minutes": (
                        int(timing["target_lead_minutes"])
                        if timing.get("target_lead_minutes") is not None
                        else "UNKNOWN"
                    ),
                    "late_generated": late,
                    "generated_at_utc": generated,
                    "prediction_cutoff_at_utc": cutoff,
                }
            )

        by_sport: dict[str, dict[str, Any]] = {}
        for sport in ACTIVE_SPORTS:
            sport_rows = [row for row in rows if row["sport"] == sport]
            by_sport[sport] = {
                "predictions": len(sport_rows),
                "late_generated": sum(bool(row["late_generated"]) for row in sport_rows),
                "competition_specific_accepted": sum(
                    row["router_status"] == "COMPETITION_SPECIFIC_ACCEPTED" for row in sport_rows
                ),
                "sport_incumbent_fallback": sum(
                    row["router_status"] == "SPORT_INCUMBENT_FALLBACK" for row in sport_rows
                ),
                "safe_prior": sum(
                    "SAFE_PRIOR" in row["router_status"].upper()
                    or "SAFE_PRIOR" in row["strategy"].upper()
                    for row in sport_rows
                ),
                "by_router_status": _group_counter(sport_rows, "router_status"),
                "by_timing_selection_status": _group_counter(sport_rows, "timing_selection_status"),
                "by_target_lead_minutes": _group_counter(sport_rows, "target_lead_minutes"),
                "by_competition_profile": _group_counter(sport_rows, "competition_profile"),
            }

        report = {
            "version": "production-route-observability-v1",
            "status": "PASS" if malformed == 0 else "BLOCKED_INVALID_FEATURES",
            "generated_at_utc": generated_at.isoformat(),
            "source": {
                "db": str(db_path.relative_to(ROOT)) if ROOT in db_path.parents else str(db_path),
                "active_sports": list(ACTIVE_SPORTS),
                "prediction_rows": len(rows),
                "malformed_feature_rows": malformed,
            },
            "runtime_integrity": {
                "late_generated_total": sum(bool(row["late_generated"]) for row in rows),
                "prediction_rows_missing_routing_metadata": sum(
                    row["router_status"] == "UNKNOWN" for row in rows
                ),
                "prediction_rows_missing_timing_metadata": sum(
                    row["timing_selection_status"] == "UNKNOWN" for row in rows
                ),
                "prediction_rows_missing_competition_profile": sum(
                    row["competition_profile"] == "UNKNOWN" for row in rows
                ),
            },
            "route_registry": _route_summary(ROOT / "results/research/competition_routes.json"),
            "timing_registry": _route_summary(ROOT / "results/research/timing_routes.json"),
            "by_router_status": _group_counter(rows, "router_status"),
            "by_strategy": _group_counter(rows, "strategy"),
            "by_timing_selection_status": _group_counter(rows, "timing_selection_status"),
            "by_target_lead_minutes": _group_counter(rows, "target_lead_minutes"),
            "by_competition_profile": _group_counter(rows, "competition_profile"),
            "by_sport": by_sport,
            "latest_prediction_generated_at_utc": max(
                (str(row["generated_at_utc"]) for row in rows if row["generated_at_utc"]),
                default=None,
            ),
            "latest_prediction_cutoff_at_utc": max(
                (str(row["prediction_cutoff_at_utc"]) for row in rows if row["prediction_cutoff_at_utc"]),
                default=None,
            ),
        }
        if malformed:
            raise RuntimeError("ROUTE_OBSERVABILITY_INVALID_FEATURES_JSON_ROWS")
        return report
    finally:
        con.close()


def main() -> int:
    report = build_report()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
