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
UA = "SevenSportResearchEngine/4.6-provenance"
SEASONS = tuple(range(2016, 2027))


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
    try:
        for p in proofs:
            url = f"{RAW_BASE}/{p['path']}"
            if p["status"] != "EXACT":
                continue
            exact += 1
            rows = con.execute(
                "SELECT snapshot_id, provenance_json FROM source_snapshot "
                "WHERE source='bleaguer-github' AND source_url=?",
                (url,),
            ).fetchall()
            for snapshot_id, old_json in rows:
                old: dict[str, Any]
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
        con.commit()
    finally:
        con.close()
    return {"exact_paths": exact, "snapshot_rows_updated": updated}


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
        "version": "github-identical-blob-v1",
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
