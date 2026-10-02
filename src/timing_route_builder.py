from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np

from src import research_cycle_v4 as base
from src.competition_profiles import resolve_profile
from src.timing_route_registry import DEFAULT_LEAD

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
OUT = ROOT / "results/research/timing_routes.json"
ACTIVE_SPORTS = ("valorant", "basketball", "volleyball", "ufc", "rizin")


def _policy() -> dict:
    return json.loads((ROOT / "config/PREDICTION_TIMING_POLICY.json").read_text(encoding="utf-8"))


def _lead_from_row(event_time: str, cutoff: str) -> float | None:
    try:
        et = __import__("datetime").datetime.fromisoformat(str(event_time).replace("Z", "+00:00"))
        ct = __import__("datetime").datetime.fromisoformat(str(cutoff).replace("Z", "+00:00"))
        if et.tzinfo is None:
            et = et.replace(tzinfo=__import__("datetime").timezone.utc)
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=__import__("datetime").timezone.utc)
        return (et - ct).total_seconds() / 60.0
    except Exception:
        return None


def _metric(y: np.ndarray, p: np.ndarray) -> dict:
    return base.metric(y, np.clip(p, 1e-6, 1 - 1e-6))


def _bootstrap(loss_delta: np.ndarray, seed_key: str, samples: int) -> dict:
    if len(loss_delta) < 2:
        return {"samples": 0, "p05_improvement": None, "probability_improvement": 0.0}
    seed = int(hashlib.sha256(seed_key.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(max(100, int(samples))):
        idx = rng.integers(0, len(loss_delta), len(loss_delta))
        vals.append(float(np.mean(loss_delta[idx])))
    arr = np.asarray(vals, dtype=float)
    return {
        "samples": int(len(arr)),
        "p05_improvement": float(np.percentile(arr, 5)),
        "median_improvement": float(np.percentile(arr, 50)),
        "probability_improvement": float(np.mean(arr > 0.0)),
    }


def _prepare_rows(con: sqlite3.Connection, sport: str, allowed_leads: set[int]) -> dict[str, dict[int, dict]]:
    query = con.execute(
        """
        SELECT fp.prediction_id,fp.event_id,fp.prediction_cutoff_at_utc,fp.generated_at_utc,
               fp.probability_side_b, e.event_time_utc,e.competition_id,e.name,
               eo.outcome_status,eo.outcome
          FROM forward_prediction fp
          JOIN event e ON e.event_id=fp.event_id
          JOIN event_outcome eo ON eo.event_id=fp.event_id
         WHERE fp.sport=? AND fp.market='winner'
           AND eo.outcome_status='VERIFIED' AND eo.outcome IN ('A','B')
           AND fp.generated_at_utc IS NOT NULL
           AND fp.prediction_cutoff_at_utc IS NOT NULL
           AND datetime(fp.generated_at_utc) <= datetime(fp.prediction_cutoff_at_utc)
           AND fp.feature_snapshot_hash IS NOT NULL AND TRIM(fp.feature_snapshot_hash)<>''
           AND fp.probability_side_a IS NOT NULL AND fp.probability_side_b IS NOT NULL
         ORDER BY e.event_time_utc,fp.generated_at_utc,fp.prediction_id
        """,
        (sport,),
    ).fetchall()

    buckets: dict[str, dict[int, dict[str, dict]]] = defaultdict(lambda: defaultdict(dict))
    for row in query:
        pid,event_id,cutoff,generated,pb,event_time,competition_id,name,status,outcome=row
        lead = _lead_from_row(event_time, cutoff)
        if lead is None:
            continue
        target = min(allowed_leads, key=lambda x: abs(float(x) - lead)) if allowed_leads else None
        if target is None or abs(float(target) - lead) > 6.0:
            continue
        profile = resolve_profile(sport, competition_id, name)
        if not profile.get("matched"):
            continue
        try:
            p = float(pb)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(p) or not 0.0 < p < 1.0:
            continue
        candidate = {
            "event_id": str(event_id),
            "time": str(event_time),
            "prediction_id": str(pid),
            "p": p,
            "y": 1 if outcome == "B" else 0,
            "competition_id": str(competition_id or ""),
            "profile_id": str(profile["profile_id"]),
            "target_lead": int(target),
            "actual_lead": float(lead),
            "generated_at": str(generated),
        }
        prev = buckets[candidate["profile_id"]][int(target)].get(str(event_id))
        if prev is None or abs(candidate["actual_lead"] - target) < abs(prev["actual_lead"] - target):
            buckets[candidate["profile_id"]][int(target)][str(event_id)] = candidate
    return {profile: {lead: items for lead, items in leads.items()} for profile, leads in buckets.items()}


def _evaluate_profile(profile_id: str, leads: dict[int, dict[str, dict]], policy: dict) -> dict:
    allowed = sorted(int(x) for x in policy.get("allowed_lead_minutes", []))
    min_rows = int(policy.get("minimums", {}).get("timing_rows", 120))
    holdout_n = max(int(policy.get("minimums", {}).get("holdout_rows", 30)), 30)
    folds_target = int(policy.get("minimums", {}).get("folds", 4))
    min_test = int(policy.get("minimums", {}).get("min_test_rows_per_fold", 15))
    default = DEFAULT_LEAD
    base_rows = leads.get(default, {})
    if len(base_rows) < min_rows:
        return {
            "status": "INSUFFICIENT_BASELINE_TIMING_DATA",
            "baseline_lead_minutes": default,
            "baseline_rows": len(base_rows),
        }

    results = {}
    for lead in allowed:
        rows = leads.get(lead, {})
        common_ids = sorted(set(base_rows) & set(rows), key=lambda eid: (rows[eid]["time"], eid))
        n = len(common_ids)
        if n < min_rows:
            results[lead] = {"status": "INSUFFICIENT_PAIRED_DATA", "paired_rows": n}
            continue
        ordered = common_ids
        hold_n = min(holdout_n, max(30, int(math.ceil(n * 0.20))))
        pre_n = n - hold_n
        if pre_n < folds_target * min_test + 30 or len({rows[eid]["time"][:4] for eid in ordered[:pre_n]}) < int(policy.get("minimums", {}).get("periods", 2)):
            results[lead] = {"status": "INSUFFICIENT_CHRONOLOGICAL_DATA", "paired_rows": n}
            continue

        pre_ids = ordered[:pre_n]
        hold_ids = ordered[pre_n:]
        idx_blocks = [b for b in np.array_split(np.arange(pre_n), folds_target) if len(b) >= min_test]
        block_details = []
        for block in idx_blocks:
            ids = [pre_ids[int(i)] for i in block.tolist()]
            yy = np.asarray([rows[eid]["y"] for eid in ids], dtype=int)
            pp = np.asarray([rows[eid]["p"] for eid in ids], dtype=float)
            bb = np.asarray([base_rows[eid]["p"] for eid in ids], dtype=float)
            if len(np.unique(yy)) < 2:
                continue
            bm = _metric(yy, bb)
            cm = _metric(yy, pp)
            block_details.append({
                "n": len(ids),
                "baseline_logloss": float(bm["logloss"]),
                "candidate_logloss": float(cm["logloss"]),
                "logloss_improvement": float(bm["logloss"] - cm["logloss"]),
                "brier_improvement": float(bm["brier"] - cm["brier"]),
                "ece_change": float(cm["ece"] - bm["ece"]),
                "start": rows[ids[0]]["time"],
                "end": rows[ids[-1]]["time"],
            })
        if len(block_details) < folds_target:
            results[lead] = {"status": "INSUFFICIENT_VALID_BLOCKS", "paired_rows": n, "folds": len(block_details)}
            continue
        pre_base_ll = float(np.mean([x["baseline_logloss"] for x in block_details]))
        pre_cand_ll = float(np.mean([x["candidate_logloss"] for x in block_details]))
        rel = (pre_base_ll - pre_cand_ll) / max(abs(pre_base_ll), 1e-12)
        non_worse = float(np.mean([x["candidate_logloss"] <= x["baseline_logloss"] + 1e-12 for x in block_details]))
        selected_research = (
            lead != default
            and rel >= float(policy.get("selection", {}).get("min_relative_logloss_improvement", 0.03))
            and non_worse >= float(policy.get("selection", {}).get("min_folds_not_worse", 0.70))
            and float(np.mean([x["brier_improvement"] for x in block_details])) >= 0.0
            and float(np.mean([x["ece_change"] for x in block_details])) <= 0.01
        )

        hold_y = np.asarray([rows[eid]["y"] for eid in hold_ids], dtype=int)
        hold_p = np.asarray([rows[eid]["p"] for eid in hold_ids], dtype=float)
        hold_b = np.asarray([base_rows[eid]["p"] for eid in hold_ids], dtype=float)
        hold_base = _metric(hold_y, hold_b)
        hold_cand = _metric(hold_y, hold_p)
        base_losses = -(hold_y * np.log(np.clip(hold_b, 1e-6, 1-1e-6)) + (1-hold_y) * np.log(np.clip(1-hold_b, 1e-6, 1-1e-6)))
        cand_losses = -(hold_y * np.log(np.clip(hold_p, 1e-6, 1-1e-6)) + (1-hold_y) * np.log(np.clip(1-hold_p, 1e-6, 1-1e-6)))
        boot = _bootstrap(base_losses - cand_losses, f"{profile_id}|{lead}|{hold_ids[0]}", int(policy.get("selection", {}).get("bootstrap_samples", 600)))
        holdout = {
            "n": len(hold_ids),
            "baseline": hold_base,
            "candidate": hold_cand,
            "logloss_improvement": float(hold_base["logloss"] - hold_cand["logloss"]),
            "brier_improvement": float(hold_base["brier"] - hold_cand["brier"]),
            "ece_change": float(hold_cand["ece"] - hold_base["ece"]),
            "bootstrap": boot,
        }
        accepted = (
            selected_research
            and holdout["n"] >= int(policy.get("minimums", {}).get("holdout_rows", 30))
            and holdout["logloss_improvement"] >= 0.0
            and holdout["brier_improvement"] >= -float(policy.get("selection", {}).get("holdout_brier_tolerance", 0.001))
            and holdout["ece_change"] <= float(policy.get("selection", {}).get("holdout_ece_tolerance", 0.01))
            and boot.get("probability_improvement", 0.0) >= float(policy.get("selection", {}).get("bootstrap_probability_improvement", 0.90))
            and float(boot.get("p05_improvement") or -1.0) > 0.0
        )
        results[lead] = {
            "status": "ACCEPTED_LOCKED_HOLDOUT" if accepted else ("PROMOTION_CANDIDATE_HOLDOUT_FAILED" if selected_research else "OOS_NO_TIMING_ROUTE"),
            "paired_rows": n,
            "pre_holdout_rows": pre_n,
            "holdout_rows": holdout_n,
            "periods": sorted({rows[eid]["time"][:4] for eid in pre_ids}),
            "folds": block_details,
            "relative_logloss_improvement_pre_holdout": float(rel),
            "fold_non_worse_rate": float(non_worse),
            "holdout": holdout,
        }

    accepted = [(lead, value) for lead, value in results.items() if value.get("status") == "ACCEPTED_LOCKED_HOLDOUT"]
    if not accepted:
        return {
            "status": "NO_ACCEPTED_NONDEFAULT_TIMING",
            "baseline_lead_minutes": default,
            "results": results,
        }
    selected_lead, selected = min(
        accepted,
        key=lambda pair: (
            -float(pair[1]["relative_logloss_improvement_pre_holdout"]),
            -float(pair[1]["holdout"]["logloss_improvement"]),
            int(pair[0]),
        ),
    )
    return {
        "status": "ACCEPTED_LOCKED_HOLDOUT",
        "baseline_lead_minutes": default,
        "selected_lead_minutes": int(selected_lead),
        "quality_status": "ACCEPTED_LOCKED_HOLDOUT",
        "holdout_used_for_selection": False,
        "pit_status": "REQUIRED_CLEAN_BY_PRODUCTION_TIMING_GATE",
        "model_scope": "timing_policy;competition_specific;frozen_holdout_accepted",
        "holdout": selected["holdout"],
        "oos": {
            "paired_rows": selected["paired_rows"],
            "pre_holdout_rows": selected["pre_holdout_rows"],
            "relative_logloss_improvement": selected["relative_logloss_improvement_pre_holdout"],
            "fold_non_worse_rate": selected["fold_non_worse_rate"],
        },
        "candidate_results": results,
        "policy": "timing route selected only from paired chronological OOS; frozen holdout is score-only; default 60m remains fail-closed fallback",
    }


def build(db_path: Path = DB, sports: list[str] | None = None) -> dict:
    policy = _policy()
    allowed = {int(x) for x in policy.get("allowed_lead_minutes", [15, 20, 30, 45, 60, 90])}
    active = list(sports or ACTIVE_SPORTS)
    con = sqlite3.connect(Path(db_path).resolve())
    try:
        pit_bad = int(con.execute(
            "SELECT COUNT(*) FROM pit_replay WHERE COALESCE(leakage_status,'UNKNOWN') NOT IN ('PASS','CLEAN')"
        ).fetchone()[0])
        report = {
            "version": "adaptive-prediction-timing-v1",
            "status": "READY" if pit_bad == 0 else "BLOCKED_PIT",
            "routes": {},
            "blocked": {},
            "pit_gate": {"status": "PASS" if pit_bad == 0 else "BLOCKED", "bad_rows": pit_bad},
            "default_lead_minutes": DEFAULT_LEAD,
            "allowed_lead_minutes": sorted(allowed),
        }
        if pit_bad:
            return report
        for sport in active:
            data = _prepare_rows(con, sport, allowed)
            for profile_id, leads in data.items():
                result = _evaluate_profile(profile_id, leads, policy)
                if result.get("status") == "ACCEPTED_LOCKED_HOLDOUT":
                    # Ensure the accepted profile truly belongs to the active sport.
                    route = dict(result)
                    route["sport"] = sport
                    route["profile_id"] = profile_id
                    route["selected_at_evaluation"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
                    report["routes"][profile_id] = route
                else:
                    report["blocked"].setdefault(sport, {})[profile_id] = result
        if report["routes"]:
            report["status"] = "READY"
        elif report["status"] == "READY":
            report["status"] = "READY_NO_ACCEPTED_ROUTES"
        return report
    finally:
        con.close()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB))
    parser.add_argument("--sport", action="append", choices=list(ACTIVE_SPORTS))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    report = build(Path(args.db), args.sport)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if str(report.get("status", "")).startswith("READY") else 1


if __name__ == "__main__":
    raise SystemExit(main())
