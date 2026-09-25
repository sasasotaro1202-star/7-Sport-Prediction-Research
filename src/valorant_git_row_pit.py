from __future__ import annotations

"""Research-only row-level PIT provenance for the public VALORANT corpus.

A current dataset snapshot cannot establish when a historical match row became
public. This module walks the public Git history of the source CSV and records
the first commit in which each row was present. The commit timestamp is used as
a conservative availability bound; it is not claimed to equal the original
web publication timestamp.
"""

import csv
import hashlib
import io
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.storage.db_v45 import connect

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
OUT = ROOT / "results/valorant_git_row_pit.json"
SOURCE = "public-vlr-dataset"
CURRENT_URL = "https://raw.githubusercontent.com/rush2pranav/valorant-pro-scene-tracker/main/data/results.csv"
REPO_URL = "https://github.com/rush2pranav/valorant-pro-scene-tracker.git"


def norm(v: object) -> str:
    return " ".join(str(v or "").strip().split())


def parse_time(v: object) -> str | None:
    s = str(v or "").strip().replace("Z", "+00:00")
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    try:
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def row_key(team1: object, team2: object, et: str | None, tournament: object = "") -> tuple[str, str, str | None, str]:
    return (norm(team1).lower(), norm(team2).lower(), et, norm(tournament).lower())


def commit_rows(repo: Path, sha: str):
    p = subprocess.run(
        ["git", "-C", str(repo), "show", f"{sha}:data/results.csv"],
        text=True, capture_output=True, check=False, timeout=90,
    )
    if p.returncode != 0:
        return []
    return list(csv.DictReader(io.StringIO(p.stdout)))


def main() -> int:
    report = {
        "status": "RESEARCH_DB_ONLY",
        "source": SOURCE,
        "source_url": CURRENT_URL,
        "repository": "rush2pranav/valorant-pro-scene-tracker",
        "path": "data/results.csv",
        "provenance_rule": "first_public_git_commit_containing_exact_match_row",
        "availability_rule": "git_committer_timestamp_as_conservative_public_availability_bound",
        "production_model_changed": False,
        "commits_scanned": 0,
        "rows_seen": 0,
        "matched_events": 0,
        "snapshot_rows_created": 0,
        "snapshot_rows_updated": 0,
        "unmatched_rows": 0,
    }
    con = connect()
    try:
        event_map = {}
        rows = con.execute(
            "SELECT event_id,event_time_utc,event_name FROM event "
            "WHERE sport='valorant' AND event_time_utc IS NOT NULL"
        ).fetchall()
        for eid, et, name in rows:
            title = norm(name)
            if " vs " in title.lower():
                a, b = title.split(" vs ", 1)
                event_map[(a.lower(), b.lower(), et, "")] = eid
                event_map[(b.lower(), a.lower(), et, "")] = eid

        with tempfile.TemporaryDirectory(prefix="valorant_pit_") as td:
            repo = Path(td) / "source"
            subprocess.run(
                ["git", "clone", "--filter=blob:none", "--no-checkout", REPO_URL, str(repo)],
                check=True, timeout=180,
            )
            hist = subprocess.run(
                ["git", "-C", str(repo), "rev-list", "--reverse", "--", "data/results.csv"],
                text=True, capture_output=True, check=True, timeout=60,
            ).stdout.splitlines()
            first_seen = {}
            for sha in hist:
                meta = subprocess.run(
                    ["git", "-C", str(repo), "show", "-s", "--format=%ct", sha],
                    text=True, capture_output=True, check=True, timeout=30,
                ).stdout.strip()
                try:
                    commit_ts = datetime.fromtimestamp(int(meta), tz=timezone.utc).isoformat()
                except Exception:
                    continue
                parsed = commit_rows(repo, sha)
                report["commits_scanned"] += 1
                report["rows_seen"] += len(parsed)
                for row in parsed:
                    team1 = row.get("team1") or row.get("team_1") or row.get("Team1")
                    team2 = row.get("team2") or row.get("team_2") or row.get("Team2")
                    et = parse_time(row.get("time_completed") or row.get("date") or row.get("completed_at"))
                    tournament = row.get("tournament_name") or row.get("tournament")
                    if not team1 or not team2 or not et:
                        continue
                    key = row_key(team1, team2, et, tournament)
                    eid = event_map.get(key)
                    if not eid:
                        # Current DB may use no tournament discriminator.
                        eid = event_map.get((norm(team1).lower(), norm(team2).lower(), et, ""))
                    if not eid or key in first_seen:
                        continue
                    first_seen[key] = (eid, sha, commit_ts)

            exact_events = {}
            for key, (eid, sha, commit_ts) in first_seen.items():
                old = exact_events.get(eid)
                if old is None or commit_ts < old["available_at_utc"]:
                    exact_events[eid] = {
                        "available_at_utc": commit_ts,
                        "commit_sha": sha,
                    }

            for eid, proof in exact_events.items():
                meta = {
                    "sport": "valorant",
                    "provenance_method": "github_row_first_presence",
                    "repository": "rush2pranav/valorant-pro-scene-tracker",
                    "path": "data/results.csv",
                    "commit_sha": proof["commit_sha"],
                    "commit_observed_at_utc": proof["available_at_utc"],
                    "exact_row_presence": True,
                    "caution": "commit timestamp is a conservative public-availability bound; original web publication timestamp is not claimed",
                }
                snapshot_id = hashlib.sha256(
                    f"valorant-row-pit|{eid}|{proof['commit_sha']}|{proof['available_at_utc']}".encode()
                ).hexdigest()[:32]
                et = con.execute(
                    "SELECT event_time_utc FROM event WHERE event_id=?",
                    (eid,),
                ).fetchone()[0]
                content_hash = hashlib.sha256(
                    json.dumps({"event_id": eid, **proof}, sort_keys=True).encode()
                ).hexdigest()
                con.execute(
                    """INSERT OR REPLACE INTO source_snapshot
                       (snapshot_id,source,source_url,retrieved_at_utc,
                        source_available_at_utc,event_time_utc,content_hash,
                        parser_version,availability_status,provenance_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        snapshot_id, SOURCE, CURRENT_URL,
                        datetime.now(timezone.utc).isoformat(),
                        proof["available_at_utc"], et, content_hash,
                        "valorant-git-row-pit-v1", "EXACT",
                        json.dumps(meta, ensure_ascii=False),
                    ),
                )
                report["snapshot_rows_created"] += 1
                report["matched_events"] += 1

            report["unmatched_rows"] = max(0, len(first_seen) - len(exact_events))
            con.commit()
    finally:
        con.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
