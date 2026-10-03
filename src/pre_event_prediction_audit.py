from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.competition_profiles import resolve_profile
from src.timing_route_registry import resolve_lead


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "PRE_EVENT_PREDICTION_POLICY.json"
OUT_DIR = ROOT / "results"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: object) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def target_event(sport: str, name: object, competition_id: object) -> dict:
    profile = resolve_profile(sport, competition_id, name)
    return profile


def audit(db_path: Path, sport: str, now: datetime, min_lead: float, max_lead: float, target_lead: int) -> dict:
    report = {
        "generated_at_utc": now.isoformat(),
        "sport": sport,
        "target_lead_minutes": target_lead,
        "default_guideline_minutes": 60,
        "timing_route_accepted_events": 0,
        "window": {"min_lead_minutes": min_lead, "max_lead_minutes": max_lead},
        "guideline_tolerance_minutes": 15,
        "guideline_only": True,
        "status": "UNKNOWN",
        "target_events_in_window": 0,
        "predicted_in_guideline_window": 0,
        "missing_predictions": [],
        "timing": {"on_time": 0, "early": 0, "late": 0},
    }
    if not db_path.is_file() or db_path.stat().st_size <= 0:
        report["status"] = "NO_DATABASE"
        return report

    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    try:
        table = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='forward_prediction'"
        ).fetchone()
        if table is None:
            report["status"] = "FORWARD_REGISTRY_MISSING"
            return report

        rows = c.execute(
            """SELECT e.event_id,e.event_time_utc,e.status,e.competition_id,
                      (SELECT COUNT(DISTINCT ep.participant_id)
                         FROM event_participant ep
                        WHERE ep.event_id=e.event_id
                          AND ep.participant_id IS NOT NULL) AS participant_count
                 FROM event e
                WHERE e.sport=?
                  AND e.event_time_utc IS NOT NULL
                ORDER BY e.event_time_utc,e.event_id""",
            (sport,),
        ).fetchall()

        target = []
        for row in rows:
            event_dt = parse_dt(row["event_time_utc"])
            if event_dt is None or event_dt <= now:
                continue
            lead = (event_dt - now).total_seconds() / 60.0
            if lead < min_lead or lead > max_lead:
                continue
            profile = target_event(sport, None, row["competition_id"])
            if not profile.get("matched"):
                continue
            target.append((row, event_dt, lead, profile))

        report["target_events_in_window"] = len(target)

        for row, event_dt, lead, profile in target:
            selected_lead, selection_status = resolve_lead(sport, profile, target_lead)
            if selection_status == "TIMING_ROUTE_ACCEPTED":
                report["timing_route_accepted_events"] += 1
            target_cutoff = event_dt - timedelta(minutes=selected_lead)
            tolerance = timedelta(minutes=15)
            earliest_cutoff = target_cutoff - tolerance
            latest_cutoff = target_cutoff + tolerance
            preds = c.execute(
                """SELECT prediction_id,created_at_utc,prediction_cutoff_at_utc,strategy,model_version
                     FROM forward_prediction
                    WHERE event_id=?
                      AND market='winner'
                      AND prediction_cutoff_at_utc BETWEEN ? AND ?
                      AND datetime(created_at_utc) <= datetime(?)
                    ORDER BY datetime(created_at_utc) DESC, prediction_id DESC""",
                (row["event_id"], earliest_cutoff.isoformat(), latest_cutoff.isoformat(), row["event_time_utc"]),
            ).fetchall()

            # A prediction is PIT-valid only when its generation timestamp is not
            # later than its own prediction cutoff. A late snapshot may exist for
            # the same event, but it cannot substitute for the latest valid
            # pre-cutoff prediction. When no valid prediction exists, fail closed.
            late_count = 0
            valid_preds = []
            for candidate in preds:
                candidate_cutoff = parse_dt(candidate["prediction_cutoff_at_utc"])
                candidate_generated = parse_dt(candidate["created_at_utc"])
                # PIT rule: candidate_generated > candidate_cutoff is invalid.
                candidate_generated_gt_cutoff = (
                    candidate_generated is not None
                    and candidate_cutoff is not None
                    and candidate_generated > candidate_cutoff
                )
                if candidate_generated_gt_cutoff:
                    late_count += 1
                    continue
                if candidate_cutoff is not None and candidate_generated is not None:
                    valid_preds.append(candidate)

            pred = valid_preds[0] if valid_preds else None

            item = {
                "event_id": row["event_id"],
                "event_time_utc": row["event_time_utc"],
                "lead_minutes_at_audit": round(float(lead), 3),
                "competition_id": row["competition_id"],
                "competition_profile": profile,
                "participant_count": int(row["participant_count"] or 0),
                "selected_lead_minutes": int(selected_lead),
                "timing_selection_status": selection_status,
                "target_cutoff_at_utc": target_cutoff.isoformat(),
                "acceptable_cutoff_range_utc": [earliest_cutoff.isoformat(), latest_cutoff.isoformat()],
            }

            if late_count:
                report["timing"]["late"] += late_count

            if pred is None:
                report["missing_predictions"].append({
                    **item,
                    "reason": (
                        "NO_PIT_VALID_PREDICTION_IN_GUIDELINE_WINDOW"
                        if late_count
                        else "NO_GUIDELINE_PREDICTION"
                    ),
                    "error_code": (
                        "NO_PIT_VALID_GUIDELINE_PREDICTION"
                        if late_count
                        else "NO_GUIDELINE_PREDICTION"
                    ),
                    "late_prediction_count": late_count,
                })
                continue

            report["predicted_in_guideline_window"] += 1
            cutoff = parse_dt(pred["prediction_cutoff_at_utc"])
            generated = parse_dt(pred["created_at_utc"])
            if generated is None or cutoff is None:
                timing_status = "UNKNOWN_GENERATION_TIME"
            else:
                timing_status = "ON_TIME" if (cutoff - generated).total_seconds() <= 120 else "EARLY"

            if timing_status == "ON_TIME":
                report["timing"]["on_time"] += 1
            elif timing_status == "EARLY":
                report["timing"]["early"] += 1

        if not target:
            report["status"] = "NO_TARGET_EVENTS_IN_WINDOW"
        elif report["missing_predictions"]:
            report["status"] = "GAP"
        else:
            report["status"] = "PASS"
        return report
    finally:
        c.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True)
    parser.add_argument("--db", default="data/db/sports_v45.sqlite")
    parser.add_argument("--target-lead-minutes", type=int, default=60)
    parser.add_argument("--min-lead-minutes", type=float, default=5.0)
    parser.add_argument("--max-lead-minutes", type=float, default=180.0)
    args = parser.parse_args()

    if args.target_lead_minutes <= 0 or args.min_lead_minutes < 0 or args.max_lead_minutes <= 0:
        raise SystemExit("invalid timing window")
    if args.min_lead_minutes > args.max_lead_minutes:
        raise SystemExit("min-lead-minutes cannot exceed max-lead-minutes")

    now = utc_now()
    report = audit(
        Path(args.db),
        args.sport,
        now,
        args.min_lead_minutes,
        args.max_lead_minutes,
        args.target_lead_minutes,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"pre_event_prediction_audit_{args.sport}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] in {
        "GAP",
        "NO_DATABASE",
        "FORWARD_REGISTRY_MISSING",
    } else 0


if __name__ == "__main__":
    raise SystemExit(main())
