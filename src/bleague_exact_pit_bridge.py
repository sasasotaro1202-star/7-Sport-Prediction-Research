from __future__ import annotations

"""Materialize explicitly publication-bounded B.LEAGUE rows into strict-PIT-safe storage."""

import argparse
import csv
import hashlib
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from src.bleaguer_git_provenance import canonical_bleaguer_event_id

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "results/research/bleague_public_availability_evidence.json"
RAW_BASE = "https://raw.githubusercontent.com/rintaromasuda/bleaguer"
SOURCE = "bleaguer-github"

# Match the existing historical B.LEAGUE parser exactly. No post-cutoff
# transformations are introduced by this bridge.
STAT_MAP = (
    ("PTS", "points"),
    ("TR", "rebounds"),
    ("AS", "assists"),
    ("ST", "steals"),
    ("BS", "blocks"),
    ("TO", "turnovers"),
    ("F2GM", "fieldGoalMade"),
    ("F2GA", "fieldGoalAttempted"),
    ("F3GM", "threePointMade"),
    ("F3GA", "threePointAttempted"),
    ("FTM", "freeThrowMade"),
    ("FTA", "freeThrowAttempted"),
)


def _iso(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d %H:%M"):
        try:
            return datetime.strptime(raw[:19], fmt).replace(
                tzinfo=timezone.utc
            ).isoformat()
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _sid(*parts: object) -> str:
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _load_evidence(path: Path) -> tuple[str, str, str]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"evidence_registry_unreadable:{type(exc).__name__}"
        ) from exc
    if not isinstance(obj, dict):
        raise RuntimeError("evidence_registry_wrong_shape")
    if obj.get("status") != "RESEARCH_EVIDENCE_ONLY":
        raise RuntimeError(
            f"evidence_registry_unsafe_status:{obj.get('status')}"
        )
    if obj.get("strict_pit_usable") is not False:
        raise RuntimeError("evidence_registry_strict_pit_flag_not_fail_closed")

    revision = obj.get("revision_evidence")
    if not isinstance(revision, dict):
        raise RuntimeError("revision_evidence_missing")
    summary_path = str(revision.get("file") or "")
    revision_sha = str(
        revision.get("revision_sha")
        or revision.get("exact_revision_sha")
        or ""
    )
    bound_raw = (revision.get("public_availability_bound") or {}).get(
        "latest_safe_utc"
    )
    bound = _iso(str(bound_raw)) if bound_raw else None

    if summary_path != "inst/extdata/games_summary_202021.csv":
        raise RuntimeError(f"unexpected_summary_path:{summary_path}")
    if not revision_sha or not bound:
        raise RuntimeError("exact_revision_or_publication_bound_missing")

    bound_dt = datetime.fromisoformat(bound)
    if bound_dt.tzinfo is None:
        raise RuntimeError("public_availability_bound_must_be_timezone_aware")
    return summary_path, revision_sha, bound


def _parse_csv_rows(payload: bytes) -> list[dict[str, str]]:
    try:
        text = payload.decode("utf-8-sig", errors="strict")
        rows = list(csv.DictReader(io.StringIO(text)))
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        raise RuntimeError(f"csv_unreadable:{type(exc).__name__}") from exc
    if not rows or not isinstance(rows[0], dict):
        raise RuntimeError("csv_empty_or_wrong_shape")
    return rows


def _default_get(url: str) -> bytes:
    # Keep the bridge importable in dependency-light control-plane/test jobs.
    # The HTTP client is needed only when the real network fetch path executes.
    import requests

    response = requests.get(
        url,
        headers={
            "User-Agent": "SevenSportResearchEngine/bleague-exact-pit-bridge"
        },
        timeout=(15, 45),
    )
    response.raise_for_status()
    return response.content


def _require_schema(con: sqlite3.Connection) -> None:
    required = {
        "event": {"event_id", "sport", "event_time_utc"},
        "event_participant": {
            "event_id", "participant_id", "team_id", "side"
        },
        "match_stats": {
            "stat_id", "event_id", "participant_id", "team_id", "sport",
            "observed_at_utc", "effective_at_utc", "stat_name", "value_num",
            "value_text", "unit", "source", "source_url", "quality_status",
            "confidence",
        },
        "source_snapshot": {
            "snapshot_id", "sport", "source", "source_url",
            "retrieved_at_utc", "source_available_at_utc", "event_time_utc",
            "content_hash", "payload_path", "parser_version",
            "availability_status", "provenance_json",
        },
    }
    for table, names in required.items():
        columns = {
            str(row[1])
            for row in con.execute(f"PRAGMA table_info({table})").fetchall()
        }
        missing = sorted(names - columns)
        if missing:
            raise RuntimeError(
                f"schema_missing:{table}:{','.join(missing)}"
            )


def _event_participants(
    con: sqlite3.Connection, event_id: str
) -> dict[str, tuple[str, str | None]]:
    rows = con.execute(
        """SELECT side,participant_id,team_id
             FROM event_participant
            WHERE event_id=?
              AND side IN ('A','B')
              AND participant_id IS NOT NULL
            ORDER BY side,participant_id,COALESCE(team_id,'')""",
        (event_id,),
    ).fetchall()
    grouped: dict[str, list[tuple[str, str | None]]] = {"A": [], "B": []}
    for side, participant_id, team_id in rows:
        grouped[str(side)].append(
            (
                str(participant_id),
                str(team_id) if team_id is not None else None,
            )
        )
    if len(grouped["A"]) != 1 or len(grouped["B"]) != 1:
        raise RuntimeError(
            f"event_participant_ambiguous:{event_id}:"
            f"A={len(grouped['A'])}:B={len(grouped['B'])}"
        )
    return {"A": grouped["A"][0], "B": grouped["B"][0]}


def _as_float(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _snapshot_id(revision_sha: str, content_hash: str) -> str:
    return _sid(
        "basketball",
        SOURCE,
        revision_sha,
        content_hash,
        "summary-202021",
    )


def materialize(
    db: Path,
    evidence_path: Path = DEFAULT_EVIDENCE,
    http_get: Callable[[str], bytes] = _default_get,
    observed_at_utc: str | None = None,
) -> dict[str, object]:
    summary_path, revision_sha, bound = _load_evidence(evidence_path)
    schedule_path = summary_path.replace("games_summary_", "games_")
    summary_url = f"{RAW_BASE}/{revision_sha}/{summary_path}"
    schedule_url = f"{RAW_BASE}/{revision_sha}/{schedule_path}"

    # Fetch the exact evidence revision explicitly. This is necessary because
    # current path history no longer exposes every old file-touching commit.
    summary_payload = http_get(summary_url)
    schedule_payload = http_get(schedule_url)
    summary_hash = hashlib.sha256(summary_payload).hexdigest()
    schedule_hash = hashlib.sha256(schedule_payload).hexdigest()
    summary_rows = _parse_csv_rows(summary_payload)
    schedule_rows = _parse_csv_rows(schedule_payload)

    summary_by_key: dict[str, dict[str, dict[str, str]]] = {}
    for row in summary_rows:
        key = str(row.get("ScheduleKey") or "").strip()
        team_id = str(row.get("TeamId") or "").strip()
        if not key or not team_id:
            continue
        bucket = summary_by_key.setdefault(key, {})
        if team_id in bucket and bucket[team_id] != row:
            raise RuntimeError(
                f"conflicting_duplicate_summary_row:{key}:{team_id}"
            )
        bucket[team_id] = row

    schedule_by_key: dict[str, dict[str, str]] = {}
    for row in schedule_rows:
        key = str(row.get("ScheduleKey") or "").strip()
        if not key:
            continue
        if key in schedule_by_key and schedule_by_key[key] != row:
            raise RuntimeError(f"conflicting_duplicate_schedule_row:{key}")
        schedule_by_key[key] = row

    con = sqlite3.connect(db)
    try:
        _require_schema(con)
        observed = observed_at_utc or datetime.now(timezone.utc).isoformat()

        # This snapshot is immutable-by-URL and exact only because the
        # availability bound comes from the separately registered evidence.
        con.execute(
            """INSERT OR REPLACE INTO source_snapshot(
                   snapshot_id,sport,source,source_url,retrieved_at_utc,
                   source_available_at_utc,event_time_utc,content_hash,
                   payload_path,parser_version,availability_status,
                   provenance_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _snapshot_id(revision_sha, summary_hash),
                "basketball",
                SOURCE,
                summary_url,
                observed,
                bound,
                None,
                summary_hash,
                summary_path,
                "bleague-exact-pit-bridge-v1",
                "EXACT",
                json.dumps(
                    {
                        "provenance_method":
                            "registered_secondary_publication_bound",
                        "publication_status":
                            "PROVEN_BY_SECONDARY_DATE_BOUND",
                        "revision_sha": revision_sha,
                        "revision_content_hash": summary_hash,
                        "schedule_revision_content_hash": schedule_hash,
                        "public_availability_bound_utc": bound,
                        "source_url_pinned_to_commit": True,
                        "strict_pit_usable": True,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )

        applied_events = 0
        applied_stats = 0
        skipped_missing_event = 0
        skipped_invalid = 0

        for key, schedule in schedule_by_key.items():
            home_id = str(schedule.get("HomeTeamId") or "").strip()
            away_id = str(schedule.get("AwayTeamId") or "").strip()
            event_time = _iso(schedule.get("Date"))
            pair = summary_by_key.get(key, {})
            if not home_id or not away_id or not event_time:
                skipped_invalid += 1
                continue

            home = pair.get(home_id)
            away = pair.get(away_id)
            if not home or not away:
                skipped_invalid += 1
                continue

            event_id = canonical_bleaguer_event_id(
                schedule, schedule_path
            )
            if not event_id:
                skipped_invalid += 1
                continue

            event_row = con.execute(
                """SELECT event_time_utc
                     FROM event
                    WHERE event_id=?
                      AND sport='basketball'""",
                (event_id,),
            ).fetchone()
            if not event_row:
                skipped_missing_event += 1
                continue

            db_event_time = _iso(event_row[0])
            if db_event_time != event_time:
                raise RuntimeError(
                    f"event_time_identity_mismatch:{key}:"
                    f"db={db_event_time}:proof={event_time}"
                )

            participants = _event_participants(con, event_id)
            for side, summary in (("A", home), ("B", away)):
                participant_id, team_id = participants[side]
                for source_col, stat_name in STAT_MAP:
                    value = _as_float(summary.get(source_col))
                    if value is None:
                        continue
                    stat_id = _sid(
                        "bleague-exact-pit-bridge-v1",
                        event_id,
                        participant_id,
                        stat_name,
                        value,
                        event_time,
                        summary_url,
                    )
                    con.execute(
                        """INSERT OR REPLACE INTO match_stats(
                               stat_id,event_id,participant_id,team_id,sport,
                               observed_at_utc,effective_at_utc,stat_name,
                               value_num,value_text,unit,source,source_url,
                               quality_status,confidence
                           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            stat_id,
                            event_id,
                            participant_id,
                            team_id,
                            "basketball",
                            observed,
                            event_time,
                            stat_name,
                            value,
                            str(value),
                            None,
                            SOURCE,
                            summary_url,
                            "EXACT",
                            1.0,
                        ),
                    )
                    applied_stats += 1
            applied_events += 1

        if applied_events == 0 or applied_stats == 0:
            con.rollback()
            raise RuntimeError(
                "NO_EXACT_PIT_ROWS_MATERIALIZED:"
                f"events={applied_events}:stats={applied_stats}:"
                f"missing_events={skipped_missing_event}:invalid={skipped_invalid}"
            )

        con.commit()
        return {
            "status": "APPLIED",
            "sport": "basketball",
            "revision_sha": revision_sha,
            "public_availability_bound_utc": bound,
            "summary_content_hash": summary_hash,
            "schedule_content_hash": schedule_hash,
            "events_applied": applied_events,
            "stats_applied": applied_stats,
            "events_skipped_missing_in_db": skipped_missing_event,
            "rows_skipped_invalid": skipped_invalid,
            "source_url": summary_url,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/db/sports_v45.sqlite")
    ap.add_argument("--evidence", default=str(DEFAULT_EVIDENCE))
    args = ap.parse_args()
    try:
        result = materialize(Path(args.db), Path(args.evidence))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "sport": "basketball",
                    "reason": f"{type(exc).__name__}:{exc}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
