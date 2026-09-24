from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
OUT = ROOT / "results/postmatch_review.json"


def _finite(x):
    try:
        return math.isfinite(float(x))
    except Exception:
        return False


def _logloss(y, p):
    p = min(max(float(p), 1e-6), 1.0 - 1e-6)
    return -math.log(p if int(y) == 1 else 1.0 - p)


def _brier(y, p):
    p = float(p)
    return (p - float(y)) ** 2


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _bucket_evidence(features):
    mi = features.get("matchday_intelligence") or {}
    counts = mi.get("evidence_counts") or {}
    total = sum(int(v or 0) for v in counts.values())
    if total <= 0:
        return "none"
    if total <= 2:
        return "low"
    if total <= 6:
        return "medium"
    return "high"


def _safe_json(value):
    try:
        return json.loads(value or "{}")
    except Exception:
        return {}


def main(db_path: Path = DB, out_path: Path = OUT):
    now = datetime.now(timezone.utc)
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            """
            SELECT fp.prediction_id,fp.event_id,fp.sport,fp.market,
                   fp.prediction_cutoff_at_utc,fp.generated_at_utc,
                   fp.probability_side_a,fp.probability_side_b,
                   fp.strategy,fp.model_version,fp.feature_version,
                   fp.features_json,fp.status,
                   e.event_time_utc,eo.outcome,eo.outcome_status,
                   eo.observed_at_utc,eo.source,eo.source_url
              FROM forward_prediction fp
              JOIN event e ON e.event_id=fp.event_id
              JOIN event_outcome eo ON eo.event_id=fp.event_id
             WHERE UPPER(COALESCE(fp.status,'OPEN'))='OPEN'
               AND eo.outcome_status='VERIFIED'
               AND eo.outcome IN ('A','B','DRAW','VOID')
               AND e.event_time_utc IS NOT NULL
               AND datetime(e.event_time_utc) < datetime(?)
             ORDER BY e.event_time_utc,fp.prediction_id
            """,
            (now.isoformat(),),
        ).fetchall()

        settled = 0
        scored = 0
        failures = 0
        records = []

        for (
            pid,eid,sport,market,cutoff,generated,pa,pb,strategy,mv,fv,
            features_json,status,event_time,outcome,outcome_status,
            observed_at,source,source_url
        ) in rows:
            try:
                settled_at = now.isoformat()
                con.execute(
                    """
                    UPDATE forward_prediction
                       SET status='SETTLED',
                           settled_outcome=?,
                           settled_at_utc=?,
                           settlement_source=?,
                           settlement_source_url=?
                     WHERE prediction_id=? AND status='OPEN'
                    """,
                    (outcome,settled_at,source,source_url,pid),
                )
                settled += 1

                rec = {
                    "prediction_id": pid,
                    "event_id": eid,
                    "sport": sport,
                    "market": market,
                    "event_time_utc": event_time,
                    "prediction_cutoff_at_utc": cutoff,
                    "generated_at_utc": generated,
                    "probability_side_a": float(pa) if _finite(pa) else None,
                    "probability_side_b": float(pb) if _finite(pb) else None,
                    "strategy": strategy,
                    "model_version": mv,
                    "feature_version": fv,
                    "outcome": outcome,
                    "outcome_status": outcome_status,
                    "settled_at_utc": settled_at,
                    "settlement_source": source,
                    "matchday_evidence_bucket": _bucket_evidence(_safe_json(features_json)),
                    "matchday_evidence_counts": (_safe_json(features_json).get("matchday_intelligence") or {}).get("evidence_counts", {}),
                }
                if outcome in ("A","B") and _finite(pb):
                    y = 1 if outcome == "B" else 0
                    rec["logloss"] = _logloss(y, pb)
                    rec["brier"] = _brier(y, pb)
                    rec["correct"] = (float(pb) >= 0.5) == bool(y)
                    scored += 1
                    if rec["correct"] is False:
                        failures += 1
                else:
                    rec["score_status"] = "UNSCORED_NON_BINARY_OUTCOME"
                records.append(rec)
            except Exception as exc:
                # Never mark a prediction settled when its review record could not
                # be assembled safely.
                con.rollback()
                records.append({
                    "prediction_id": pid,
                    "event_id": eid,
                    "status": "REVIEW_ERROR",
                    "reason": type(exc).__name__,
                })
        con.commit()

        settled_rows = con.execute(
            """
            SELECT sport,strategy,settled_outcome,probability_side_b,features_json
              FROM forward_prediction
             WHERE status='SETTLED'
             ORDER BY settled_at_utc DESC
             LIMIT 2000
            """
        ).fetchall()

        groups = defaultdict(lambda: {"n":0,"scored":0,"logloss":0.0,"brier":0.0,"correct":0})
        for sport,strategy,outcome,pb,features_json in settled_rows:
            g = groups[(sport, strategy or "unknown")]
            g["n"] += 1
            if outcome in ("A","B") and _finite(pb):
                y = 1 if outcome == "B" else 0
                g["scored"] += 1
                g["logloss"] += _logloss(y,pb)
                g["brier"] += _brier(y,pb)
                g["correct"] += int((float(pb) >= 0.5) == bool(y))

        summary = {}
        for (sport,strategy), g in groups.items():
            n = g["scored"]
            summary[f"{sport}|{strategy}"] = {
                "settled_rows": g["n"],
                "scored_rows": n,
                "logloss": g["logloss"]/n if n else None,
                "brier": g["brier"]/n if n else None,
                "accuracy": g["correct"]/n if n else None,
            }

        report = {
            "generated_at_utc": _utcnow(),
            "settled_now": settled,
            "scored_now": scored,
            "incorrect_now": failures,
            "recent_summary_limit": 2000,
            "recent_summary": summary,
            "recent_settled_records": records[-500:],
            "policy": (
                "postmatch_review_only; verified outcomes only; binary A/B scoring only; "
                "no parameter update; no automatic promotion; matchday evidence is attribution metadata"
            ),
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
