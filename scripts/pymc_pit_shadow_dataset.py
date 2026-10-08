from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_SPORTS = ("basketball", "volleyball", "ufc", "rizin", "valorant")
MIN_PIT_GAP = timedelta(minutes=60)
SHADOW_BUILDER_VERSION = "v1"


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def build(db_path: Path, sport: str | None = None) -> dict:
    selected_sports = (sport,) if sport else ACTIVE_SPORTS
    if any(s not in ACTIVE_SPORTS for s in selected_sports):
        raise ValueError(f"unsupported active sport: {selected_sports}")
    if not db_path.is_file() or db_path.stat().st_size <= 0:
        return {
            "status": "DEFERRED_NO_DB",
            "research_only": True,
            "production_dependency": False,
            "automatic_promotion": False,
        }

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in selected_sports)
        events = {
            r["event_id"]: dict(r)
            for r in con.execute(
                f"SELECT event_id,sport,competition_id,event_time_utc "
                f"FROM event WHERE sport IN ({placeholders}) AND event_time_utc IS NOT NULL",
                selected_sports,
            )
        }
        participants = {}
        for r in con.execute(
            f"SELECT event_id,side,participant_id,team_id "
            f"FROM event_participant "
            f"WHERE side IN ('A','B') AND event_id IN "
            f"(SELECT event_id FROM event WHERE sport IN ({placeholders})) "
            f"ORDER BY event_id,side",
            selected_sports,
        ):
            participants.setdefault(r["event_id"], {})[r["side"]] = dict(r)

        outcomes = {
            r["event_id"]: dict(r)
            for r in con.execute(
                f"SELECT event_id,outcome FROM event_outcome "
                f"WHERE sport IN ({placeholders}) "
                "AND outcome_status='VERIFIED' AND outcome IN ('A','B')",
                selected_sports,
            )
        }

        replays = con.execute(
            f"""
            SELECT p.replay_id,p.event_id,p.prediction_cutoff_at_utc,
                   p.replay_status,p.leakage_status,p.dataset_hash,p.git_commit_sha
              FROM pit_replay p
              JOIN event e ON e.event_id=p.event_id
             WHERE e.sport IN ({placeholders})
               AND p.replay_status='REPLAYABLE'
               AND p.leakage_status IN ('CLEAN','PASS')
             ORDER BY p.event_id,p.prediction_cutoff_at_utc DESC,p.replay_id DESC
            """,
            selected_sports,
        ).fetchall()

        chosen = {}
        for row in replays:
            chosen.setdefault(row["event_id"], dict(row))

        rows = []
        for event_id, replay in chosen.items():
            event = events.get(event_id)
            sides = participants.get(event_id, {})
            outcome = outcomes.get(event_id)
            if not event or not outcome or "A" not in sides or "B" not in sides:
                continue

            cutoff = parse_dt(replay["prediction_cutoff_at_utc"])
            event_time = parse_dt(event["event_time_utc"])
            if cutoff + MIN_PIT_GAP > event_time:
                raise RuntimeError(f"PIT_GAP_FAIL:{event_id}")

            features = {}
            source_ids = set()
            feature_rows = con.execute(
                """
                SELECT snapshot_id,feature_name,value_num,value_text,
                       source_observation_ids,leakage_status
                  FROM pit_feature_snapshot
                 WHERE replay_id=?
                 ORDER BY feature_name,snapshot_id
                """,
                (replay["replay_id"],),
            ).fetchall()

            if not feature_rows:
                continue

            for fr in feature_rows:
                if fr["leakage_status"] not in ("CLEAN", "PASS"):
                    raise RuntimeError(
                        f"FEATURE_LEAKAGE_FAIL:{event_id}:{fr['feature_name']}"
                    )
                if fr["value_num"] is not None:
                    features[fr["feature_name"]] = float(fr["value_num"])
                elif fr["value_text"] is not None:
                    features[fr["feature_name"]] = fr["value_text"]

                try:
                    ids = json.loads(fr["source_observation_ids"] or "[]")
                except Exception as exc:
                    raise RuntimeError(
                        f"SOURCE_IDS_INVALID:{event_id}:{fr['feature_name']}"
                    ) from exc
                if not isinstance(ids, list) or not ids:
                    raise RuntimeError(
                        f"SOURCE_IDS_EMPTY:{event_id}:{fr['feature_name']}"
                    )
                source_ids.update(str(x) for x in ids)

            for snapshot_id in sorted(source_ids):
                source = con.execute(
                    """
                    SELECT availability_status,source_available_at_utc,retrieved_at_utc
                      FROM source_snapshot
                     WHERE snapshot_id=?
                    """,
                    (snapshot_id,),
                ).fetchone()
                if (
                    not source
                    or source["availability_status"] != "EXACT"
                    or not source["source_available_at_utc"]
                ):
                    raise RuntimeError(
                        f"PIT_SOURCE_NOT_EXACT:{event_id}:{snapshot_id}"
                    )
                if parse_dt(source["source_available_at_utc"]) > cutoff:
                    raise RuntimeError(
                        f"FUTURE_SOURCE_FAIL:{event_id}:{snapshot_id}"
                    )

            rows.append(
                {
                    "event_id": event_id,
                    "sport": event["sport"],
                    "competition_id": event["competition_id"],
                    "event_time_utc": event["event_time_utc"],
                    "prediction_cutoff_at_utc": replay[
                        "prediction_cutoff_at_utc"
                    ],
                    "team_a": sides["A"]["team_id"] or sides["A"]["participant_id"],
                    "team_b": sides["B"]["team_id"] or sides["B"]["participant_id"],
                    "participant_a": sides["A"]["participant_id"],
                    "participant_b": sides["B"]["participant_id"],
                    "outcome": outcome["outcome"],
                    "feature_count": len(features),
                    "features": features,
                    "source_snapshot_ids": sorted(source_ids),
                    "dataset_hash": replay["dataset_hash"],
                    "replay_git_commit_sha": replay["git_commit_sha"],
                }
            )

        rows.sort(key=lambda row: (row["event_time_utc"], row["event_id"]))
        counts = {}
        for row in rows:
            counts[row["sport"]] = counts.get(row["sport"], 0) + 1

        payload = {
            "status": "READY" if rows else "DEFERRED_NO_ELIGIBLE_PIT_ROWS",
            "research_only": True,
            "production_dependency": False,
            "automatic_promotion": False,
            "active_sports": list(selected_sports),
            "dataset_scope": "SPORT_SINGLE" if sport else "ACTIVE_ALL",
            "row_count": len(rows),
            "rows_by_sport": counts,
            "minimum_pit_gap_minutes": 60,
            "chronological_order_verified": all(
                rows[i]["event_time_utc"] <= rows[i + 1]["event_time_utc"]
                for i in range(len(rows) - 1)
            ),
            "outcome_used_only_as_label": True,
            "future_source_check": True,
            "feature_leakage_check": True,
            "next_gates": [
                "PyMC real-event Shadow fit",
                "chronological OOS/WFO",
                "calibration",
                "robustness",
                "frozen holdout",
                "shadow comparison",
            ],
            "rows": rows,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        payload["dataset_sha256"] = digest
        return payload
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/db/sports_v45.sqlite")
    parser.add_argument("--sport", choices=ACTIVE_SPORTS, default=None)
    parser.add_argument(
        "--out", default="results/research/pymc_pit_shadow_dataset.json"
    )
    args = parser.parse_args()
    report = build(Path(args.db), sport=args.sport)
    output = ROOT / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(
        {
            "status": report["status"],
            "row_count": report.get("row_count", 0),
            "rows_by_sport": report.get("rows_by_sport", {}),
            "dataset_sha256": report.get("dataset_sha256"),
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
