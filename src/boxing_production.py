from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from src.storage.db_v45 import connect, utcnow
from src.seven_sport_production import HTTP, upsert_event, upsert_participant, upsert_ep, add_snapshot

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "v45" / "boxing_coverage.json"

OPEN_BOXING_BOUTS = "https://raw.githubusercontent.com/edhwright/open-boxing/main/src/db/data/bouts.csv"
OPEN_BOXING_CHAMPIONS = "https://raw.githubusercontent.com/edhwright/open-boxing/main/src/db/data/champions.csv"
OPEN_BOXING_SCHEDULED = "https://openboxing.org/api/bouts/scheduled.json"

CANDIDATES = [
    {
        "name": "Open Boxing / edhwright",
        "url": "https://github.com/edhwright/open-boxing",
        "role": "free/open historical boxing dataset",
        "pit_status": "HISTORICAL_LABELS_AVAILABLE; PUBLICATION_TIME_UNPROVEN",
    },
    {
        "name": "Boxing Undefeated / open-boxing-data",
        "url": "https://github.com/boxingundefeated/open-boxing-data",
        "role": "free/open boxing-data project",
        "pit_status": "UNPROVEN",
    },
    {
        "name": "BoxingScene",
        "url": "https://www.boxingscene.com/",
        "role": "public current schedule/results candidate",
        "pit_status": "UNPROVEN",
    },
    {
        "name": "BoxRec-compatible tooling",
        "url": "https://github.com/boxing/boxrec",
        "role": "unofficial BoxRec access tooling",
        "pit_status": "UNPROVEN_AND_TERMS_RISK",
    },
]


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).isoformat()
        except Exception:
            return None


def probe(h: HTTP, url: str) -> dict:
    try:
        raw, retrieved, headers = h.get(url)
        return {
            "reachable": True,
            "retrieved_at_utc": retrieved,
            "bytes": len(raw.encode("utf-8", errors="ignore")),
            "etag": headers.get("ETag") or headers.get("etag"),
        }
    except Exception as exc:
        return {"reachable": False, "error": type(exc).__name__}


def ingest_history(c, h: HTTP) -> dict:
    raw, retrieved, _ = h.get(OPEN_BOXING_BOUTS)
    ph = hashlib.sha256(raw.encode()).hexdigest()
    add_snapshot(c, "boxing", "openboxing", OPEN_BOXING_BOUTS, retrieved, None, ph, "UNVERIFIABLE")
    rows = list(csv.DictReader(io.StringIO(raw)))
    imported = 0
    outcomes = 0
    skipped = 0

    for row in rows:
        bout_id = str(row.get("bout_id") or "").strip()
        date = str(row.get("date") or "").strip()
        a_name = str(row.get("boxer_a_name") or "").strip()
        b_name = str(row.get("boxer_b_name") or "").strip()
        status = str(row.get("status") or "").strip().upper()
        winner = str(row.get("winner") or "").strip().upper()
        if not bout_id or not date or not a_name or not b_name:
            skipped += 1
            continue
        et = parse_date(date)
        if not et:
            skipped += 1
            continue
        weight_class = str(row.get("weight_class") or "").strip()
        weight_lb = str(row.get("weight_lb") or "").strip()
        competition = f"boxing:{weight_class}:{weight_lb}".strip(":")
        event_name = f"{a_name} vs {b_name}"
        eid = upsert_event(
            c, "boxing", event_name, et, "openboxing", OPEN_BOXING_BOUTS,
            "COMPLETED" if status == "FINISHED" else status or "SCHEDULED",
            competition=competition, season=date[:4]
        )
        pid_a = upsert_participant(c, "boxing", a_name, "fighter")
        pid_b = upsert_participant(c, "boxing", b_name, "fighter")
        upsert_ep(c, eid, pid_a, pid_a, "A", "fight", "openboxing", OPEN_BOXING_BOUTS)
        upsert_ep(c, eid, pid_b, pid_b, "B", "fight", "openboxing", OPEN_BOXING_BOUTS)

        if status == "FINISHED":
            outcome = "A" if winner == "BOXER A" else "B" if winner == "BOXER B" else "DRAW" if winner == "DRAW" else "VOID"
            try:
                total_rounds = float(row.get("total_rounds")) if row.get("total_rounds") else None
                scheduled_rounds = float(row.get("scheduled_rounds")) if row.get("scheduled_rounds") else None
            except Exception:
                total_rounds = scheduled_rounds = None
            c.execute(
                """INSERT OR REPLACE INTO event_outcome
                   (event_id,sport,side_a_participant_id,side_b_participant_id,
                    outcome,score_a,score_b,outcome_status,source,source_url,
                    observed_at_utc,quality_status,reason)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    eid, "boxing", pid_a, pid_b, outcome,
                    None, None, "VERIFIED", "openboxing", OPEN_BOXING_BOUTS,
                    utcnow(), "HISTORICAL_LABEL_EVENT_REALIZED",
                    "Historical teacher label from Open Boxing; source publication timing is unproven and is never used as feature PIT evidence.",
                ),
            )
            outcomes += 1
            for stat_name, val in (
                ("scheduled_rounds", scheduled_rounds),
                ("total_rounds", total_rounds),
            ):
                if val is not None:
                    # These are event metadata, not pre-fight statistics. They stay
                    # outside strict feature history until source availability is proven.
                    c.execute(
                        """INSERT OR REPLACE INTO match_stats
                           (stat_id,event_id,participant_id,team_id,sport,observed_at_utc,
                            effective_at_utc,stat_name,value_num,value_text,unit,source,
                            source_url,quality_status,confidence)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            hashlib.sha256(f"{eid}|{stat_name}|{val}".encode()).hexdigest()[:32],
                            eid, pid_a, pid_a, "boxing", utcnow(), et,
                            stat_name, val, str(val), None, "openboxing",
                            OPEN_BOXING_BOUTS, "UNVERIFIABLE", None,
                        ),
                    )
        imported += 1

    c.commit()
    return {"rows": len(rows), "imported_events": imported, "verified_outcomes": outcomes, "skipped": skipped, "retrieved_at_utc": retrieved}


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest-history", action="store_true")
    ap.add_argument("--probe-only", action="store_true")
    a = ap.parse_args()

    h = HTTP()
    report = {
        "sport": "boxing",
        "status": "DEFERRED_PIT",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "prediction_cutoff_rule": "event_time_minus_60m",
        "provenance_rule": "retrieval time is never treated as historical publication availability",
        "production_model_enabled": False,
        "history_ingestion": None,
        "candidate_sources": [],
        "reason": "Boxing history may be used as realized teacher labels after the event, but no historical pre-fight feature source is admitted until source availability before the prediction cutoff is proven.",
    }

    for candidate in CANDIDATES:
        report["candidate_sources"].append({**candidate, "probe": probe(h, candidate["url"])})

    if a.ingest_history:
        c = connect()
        try:
            report["history_ingestion"] = ingest_history(c, h)
        except Exception as exc:
            report["history_ingestion"] = {"status": "DEGRADED", "error": type(exc).__name__}
        finally:
            c.close()
    elif not a.probe_only:
        # Default behavior remains a read-only provenance guard.
        pass

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
