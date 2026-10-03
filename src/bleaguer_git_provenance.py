from __future__ import annotations

"""Prove historical observability of the B.LEAGUE GitHub corpus without weakening PIT.

A current raw GitHub URL is not treated as historically observable by itself.
For each immutable season CSV we:
  1. hash the current content,
  2. inspect the repository's commit history for that path,
  3. fetch candidate historical revisions,
  4. find the earliest GitHub commit whose blob content exactly matches the
     current content, and
  5. only then mark matching source_snapshot rows EXACT.

This proves that the exact bytes currently used by the collector were present
in the public repository by the GitHub commit timestamp. If the content was
later rewritten, or history cannot be established, the snapshot remains
UNVERIFIABLE and research stays deferred.
"""

import argparse
import csv
import io
import concurrent.futures
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data/db/sports_v45.sqlite"
OWNER = "rintaromasuda"
REPO = "bleaguer"
BRANCH = "master"
RAW_BASE = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}"
API_BASE = f"https://api.github.com/repos/{OWNER}/{REPO}/commits"
UA = "SevenSportResearchEngine/4.7-provenance-row"
SEASONS = tuple(range(2016, 2027))


def event_id_from_schedule_key(schedule_key: str | None) -> str | None:
    key = str(schedule_key or "").strip()
    if not key:
        return None
    return sha256_bytes(f"basketball|bleaguer|{key}".encode())[:32]


def csv_row_signature(row: dict[str, Any]) -> str:
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(payload.encode("utf-8"))


def _commit_observed_at(commit: dict[str, Any]) -> str | None:
    return iso(
        ((commit.get("commit") or {}).get("committer") or {}).get("date")
        or ((commit.get("commit") or {}).get("author") or {}).get("date")
    )


def _parse_csv_rows(raw: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def row_event_provenance(
    s: requests.Session,
    path: str,
    current: bytes,
    commits: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return exact-current-row availability for two-sided B.LEAGUE summaries."""
    if "games_summary_" not in path:
        return {}

    wanted: dict[tuple[str, str], tuple[str, str]] = {}
    for row in _parse_csv_rows(current):
        key = str(row.get("ScheduleKey") or "").strip()
        team = str(row.get("TeamId") or "").strip()
        event_id = event_id_from_schedule_key(key)
        if key and team and event_id:
            wanted[(key, team)] = (event_id, csv_row_signature(row))
    if not wanted:
        return {}

    found: dict[tuple[str, str], tuple[str, str]] = {}
    ordered = sorted(
        commits,
        key=lambda item: _commit_observed_at(item) or "9999-12-31T23:59:59+00:00",
    )
    for commit in ordered:
        sha = commit.get("sha")
        observed = _commit_observed_at(commit)
        if not sha or not observed:
            continue
        try:
            rows = _parse_csv_rows(
                get_bytes(
                    s,
                    f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{sha}/{path}",
                )
            )
        except Exception:
            continue

        present = {
            (
                str(row.get("ScheduleKey") or "").strip(),
                str(row.get("TeamId") or "").strip(),
            ): csv_row_signature(row)
            for row in rows
        }
        for key, (event_id, signature) in wanted.items():
            if key not in found and present.get(key) == signature:
                found[key] = (observed, sha)
        if len(found) == len(wanted):
            break

    grouped: dict[str, list[tuple[str, str]]] = {}
    for key, (event_id, _signature) in wanted.items():
        observation = found.get(key)
        if observation is not None:
            grouped.setdefault(event_id, []).append(observation)

    result: dict[str, dict[str, Any]] = {}
    for event_id, observations in grouped.items():
        # Require both team rows before declaring the event's summary available.
        if len(observations) < 2:
            continue
        latest_at = max(observations, key=lambda item: item[0])[0]
        result[event_id] = {
            "source_available_at_utc": latest_at,
            "provenance_commit_shas": sorted({sha for _date, sha in observations}),
            "row_count_proven": len(observations),
        }
    return result



def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso(value: str | None) -> str | None:
    if not value:
        return None
    s = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/vnd.github+json"})
    return s


def get_json(s: requests.Session, url: str, params: dict[str, Any] | None = None) -> Any:
    last: Exception | None = None
    for attempt in range(5):
        try:
            r = s.get(url, params=params, timeout=30)
            if r.status_code == 403 and r.headers.get("Retry-After"):
                time.sleep(min(60, int(r.headers["Retry-After"])))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            last = exc
            if attempt < 4:
                time.sleep(1.5 * (2 ** attempt))
    raise last or RuntimeError("GitHub API request failed")


def get_bytes(s: requests.Session, url: str) -> bytes:
    last: Exception | None = None
    for attempt in range(5):
        try:
            r = s.get(url, timeout=30)
            r.raise_for_status()
            return r.content
        except requests.RequestException as exc:
            last = exc
            if attempt < 4:
                time.sleep(1.5 * (2 ** attempt))
    raise last or RuntimeError("GitHub raw request failed")


def commit_history(s: requests.Session, path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in range(1, 11):
        rows = get_json(
            s,
            API_BASE,
            {"path": path, "per_page": 100, "page": page},
        )
        if not rows:
            break
        out.extend(rows)
        if len(rows) < 100:
            break
    return out


def prove_path(path: str) -> dict[str, Any]:
    s = session()
    current_url = f"{RAW_BASE}/{path}"
    try:
        current = get_bytes(s, current_url)
    except requests.HTTPError as exc:
        # A season file that no longer exists is not a provenance failure.
        # Keep it UNVERIFIABLE so the strict PIT gate can safely defer it.
        return {
            "path": path,
            "status": "UNVERIFIABLE",
            "reason": f"current source unavailable: {exc}",
            "checked_at_utc": utcnow(),
        }
    current_hash = sha256_bytes(current)
    commits = commit_history(s, path)
    row_provenance = row_event_provenance(s, path, current, commits)

    # GitHub returns newest-first. Walk all known revisions, but only accept
    # the earliest revision whose bytes are exactly the bytes we use today.
    matches: list[tuple[str, str]] = []
    for c in commits:
        sha = c.get("sha")
        if not sha:
            continue
        try:
            b = get_bytes(s, f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{sha}/{path}")
        except Exception:
            continue
        if sha256_bytes(b) == current_hash:
            date = (
                ((c.get("commit") or {}).get("committer") or {}).get("date")
                or ((c.get("commit") or {}).get("author") or {}).get("date")
            )
            if date:
                matches.append((sha, date))

    if not matches:
        return {
            "path": path,
            "status": "UNVERIFIABLE",
            "current_hash": current_hash,
            "reason": "no historical GitHub commit with identical bytes was found",
            "checked_at_utc": utcnow(),
            "commits_checked": len(commits),
            "row_event_provenance": row_provenance,
        }

    earliest_sha, earliest_date = sorted(matches, key=lambda x: x[1])[0]
    return {
        "path": path,
        "status": "EXACT",
        "current_hash": current_hash,
        "source_available_at_utc": iso(earliest_date),
        "provenance_commit_sha": earliest_sha,
        "repository": f"{OWNER}/{REPO}",
        "branch": BRANCH,
        "checked_at_utc": utcnow(),
        "commits_checked": len(commits),
        "matching_commits": len(matches),
        "row_event_provenance": row_provenance,
    }


def target_paths() -> list[str]:
    # Only immutable files that actually exist in the public corpus are
    # candidates. Missing seasons are explicitly UNVERIFIABLE, never fatal.
    return [
        f"inst/extdata/games_{suffix}.csv"
        for suffix in ("201617","201718","201819","201920","202021","202122")
    ] + [
        f"inst/extdata/games_summary_{suffix}.csv"
        for suffix in ("201617","201718","201819","201920","202021","202122")
    ]


def apply(db: Path, proofs: list[dict[str, Any]]) -> dict[str, Any]:
    con = sqlite3.connect(db)
    updated = 0
    exact = 0
    row_exact_snapshots = 0
    row_exact_events = 0
    try:
        for p in proofs:
            url = f"{RAW_BASE}/{p['path']}"

            if p["status"] == "EXACT":
                exact += 1
                rows = con.execute(
                    "SELECT snapshot_id, provenance_json FROM source_snapshot "
                    "WHERE source='bleaguer-github' AND source_url=?",
                    (url,),
                ).fetchall()
                for snapshot_id, old_json in rows:
                    try:
                        old = json.loads(old_json) if old_json else {}
                    except Exception:
                        old = {}
                    old.update({
                        "provenance_method": "github_commit_identical_blob",
                        "repository": p["repository"],
                        "branch": p["branch"],
                        "commit_sha": p["provenance_commit_sha"],
                        "commit_observed_at_utc": p["source_available_at_utc"],
                        "exact_current_blob": True,
                    })
                    con.execute(
                        "UPDATE source_snapshot SET source_available_at_utc=?, "
                        "availability_status='EXACT', provenance_json=? WHERE snapshot_id=?",
                        (p["source_available_at_utc"], json.dumps(old, ensure_ascii=False), snapshot_id),
                    )
                    updated += 1

            row_map = p.get("row_event_provenance") or {}
            if not row_map:
                continue
            rows = con.execute(
                "SELECT snapshot_id, provenance_json FROM source_snapshot "
                "WHERE source='bleaguer-github' AND source_url=?",
                (url,),
            ).fetchall()
            if not rows:
                continue

            row_exact_events += len(row_map)
            for snapshot_id, old_json in rows:
                try:
                    old = json.loads(old_json) if old_json else {}
                except Exception:
                    old = {}
                existing = old.get("row_event_provenance")
                if not isinstance(existing, dict):
                    existing = {}
                existing.update(row_map)
                old["row_event_provenance"] = existing
                old["row_provenance_version"] = "v1"
                old["provenance_method"] = (
                    "github_commit_identical_blob"
                    if p["status"] == "EXACT"
                    else "github_identical_row_history"
                )
                old["repository"] = f"{OWNER}/{REPO}"
                old["branch"] = BRANCH

                if p["status"] == "EXACT":
                    con.execute(
                        "UPDATE source_snapshot SET provenance_json=? WHERE snapshot_id=?",
                        (json.dumps(old, ensure_ascii=False), snapshot_id),
                    )
                else:
                    # Partial row proof must never masquerade as whole-file EXACT.
                    con.execute(
                        "UPDATE source_snapshot SET availability_status='ROW_EXACT', "
                        "provenance_json=? WHERE snapshot_id=?",
                        (json.dumps(old, ensure_ascii=False), snapshot_id),
                    )
                row_exact_snapshots += 1

        con.commit()
    finally:
        con.close()
    return {
        "exact_paths": exact,
        "snapshot_rows_updated": updated,
        "row_exact_snapshots": row_exact_snapshots,
        "row_exact_events": row_exact_events,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--season", type=int, action="append")
    args = ap.parse_args()

    paths = target_paths()
    if args.season:
        wanted = set(args.season)
        paths = [
            p for p in paths
            if any(p.endswith(f"games_{s}{str(s + 1)[-2:]}.csv") or
                   p.endswith(f"games_summary_{s}{str(s + 1)[-2:]}.csv") for s in wanted)
        ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        proofs = list(ex.map(prove_path, paths))

    result = {
        "version": "github-identical-row-v2",
        "checked_at_utc": utcnow(),
        "paths": proofs,
        "apply": apply(Path(args.db), proofs),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # This tool is deliberately non-failing for unverifiable history: it must
    # leave those rows deferred rather than blocking the entire production run.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
