from __future__ import annotations

"""Prove historical observability of the B.LEAGUE GitHub corpus without weakening PIT.

A current raw GitHub URL is not treated as historically observable by itself.
For each immutable season CSV we:
  1. hash the current content,
  2. inspect the repository's commit history for that path,
  3. fetch candidate historical revisions,
  4. find historical GitHub commits whose blob content exactly matches the
     current content, and
  5. record that as VERSION_EXACT evidence only.

A Git commit timestamp is not, by itself, proof that the bytes were publicly
reachable at that timestamp: a commit can be pushed after its authored/committed
time. Therefore this tool deliberately never converts Git commit time into
source_available_at_utc or strict-PIT EXACT status. Separate public-availability
evidence (for example an independently timestamped archive capture) is required
before PIT can consume the snapshot.
"""

import argparse
import concurrent.futures
import csv
import hashlib
import io
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

# Feature values imported from games_summary_*.csv. Provenance is tracked at
# event-level and pinned to a historical Git commit so pit_replay_builder can
# use the normal source_snapshot/source_url contract without weakening PIT.
SUMMARY_ID_FIELDS = ("ScheduleKey", "TeamId", "Date")
SUMMARY_NUMERIC_FIELDS = (
    "PTS", "TR", "AS", "ST", "BS", "TO",
    "F2GM", "F2GA", "F3GM", "F3GA", "FTM", "FTA",
)
SUMMARY_FIELDS = SUMMARY_ID_FIELDS + SUMMARY_NUMERIC_FIELDS


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


def _commit_date(commit: dict[str, Any]) -> str | None:
    return (
        ((commit.get("commit") or {}).get("committer") or {}).get("date")
        or ((commit.get("commit") or {}).get("author") or {}).get("date")
    )


def _canonical_summary_value(field: str, value: Any) -> str:
    raw = "" if value is None else str(value).strip()
    if field in SUMMARY_NUMERIC_FIELDS:
        if not raw:
            return ""
        try:
            return format(float(raw), ".12g")
        except (TypeError, ValueError):
            return f"INVALID:{raw}"
    return raw


def summary_row_fingerprint(row: dict[str, Any]) -> str:
    payload = tuple(_canonical_summary_value(field, row.get(field)) for field in SUMMARY_FIELDS)
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def summary_targets_from_bytes(data: bytes) -> dict[str, dict[str, str]]:
    """Return only unambiguous two-team event rows from the current summary file."""
    groups: dict[str, dict[str, str]] = {}
    ambiguous: set[str] = set()
    try:
        text = data.decode("utf-8-sig", errors="strict")
        for row in csv.DictReader(io.StringIO(text)):
            schedule_key = str(row.get("ScheduleKey") or "").strip()
            team_id = str(row.get("TeamId") or "").strip()
            if not schedule_key or not team_id:
                continue
            fp = summary_row_fingerprint(row)
            bucket = groups.setdefault(schedule_key, {})
            prior = bucket.get(team_id)
            if prior is not None and prior != fp:
                ambiguous.add(schedule_key)
                continue
            bucket[team_id] = fp
    except (UnicodeDecodeError, csv.Error, ValueError):
        return {}
    return {
        key: value
        for key, value in groups.items()
        if key not in ambiguous and len(value) == 2
    }


def match_summary_revision(
    data: bytes,
    targets: dict[str, dict[str, str]],
    remaining: set[str],
) -> dict[str, set[str]]:
    """Find target events whose two current feature rows coexist in this revision."""
    if not remaining:
        return {}
    matched: dict[str, set[str]] = {}
    try:
        text = data.decode("utf-8-sig", errors="strict")
        for row in csv.DictReader(io.StringIO(text)):
            schedule_key = str(row.get("ScheduleKey") or "").strip()
            if schedule_key not in remaining:
                continue
            team_id = str(row.get("TeamId") or "").strip()
            expected = targets.get(schedule_key, {})
            if team_id in expected and summary_row_fingerprint(row) == expected[team_id]:
                matched.setdefault(schedule_key, set()).add(team_id)
    except (UnicodeDecodeError, csv.Error, ValueError):
        return {}
    return {
        schedule_key: teams
        for schedule_key, teams in matched.items()
        if len(teams) == 2 and set(targets.get(schedule_key, {})) == teams
    }


def find_first_summary_provenance(
    current_bytes: bytes,
    revisions: list[tuple[str, str, bytes]],
) -> dict[str, dict[str, Any]]:
    """Return the earliest commit where both current feature rows coexist exactly."""
    targets = summary_targets_from_bytes(current_bytes)
    remaining = set(targets)
    out: dict[str, dict[str, Any]] = {}
    for commit_sha, commit_date, revision_bytes in sorted(revisions, key=lambda x: x[1]):
        if not remaining:
            break
        matched = match_summary_revision(revision_bytes, targets, remaining)
        for schedule_key in matched:
            out[schedule_key] = {
                "schedule_key": schedule_key,
                "provenance_commit_sha": commit_sha,
                "commit_timestamp_utc": iso(commit_date),
                "publication_status": "UNPROVEN",
                "content_hash": sha256_bytes(revision_bytes),
                "matched_team_ids": sorted(targets[schedule_key]),
            }
            remaining.remove(schedule_key)
    return out


def pinned_raw_url(path: str, commit_sha: str) -> str:
    return f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{commit_sha}/{path}"


def secondary_publication_bound(path: str, commit_sha: str) -> dict[str, Any] | None:
    """Return only explicitly registered conservative public-availability bounds."""
    evidence_path = ROOT / "results" / "research" / "bleague_public_availability_evidence.json"
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    for item in payload.get("evidence") or []:
        revision = item.get("revision_evidence") or {}
        if str(revision.get("exact_revision_sha") or "") != str(commit_sha):
            continue
        bound_info = revision.get("public_availability_bound") or {}
        if str(bound_info.get("precision") or "") != "DATE_ONLY":
            continue
        bound_ts = iso(str(bound_info.get("latest_safe_utc") or ""))
        commit_ts = iso(str(revision.get("revision_commit_timestamp_utc") or ""))
        next_touch = iso(str(revision.get("next_file_touch_timestamp_utc") or ""))
        if not bound_ts or not commit_ts or bound_ts < commit_ts:
            continue
        if next_touch and bound_ts >= next_touch:
            continue
        if str(revision.get("no_intervening_file_touch_between_revision_and_independent_publication")).lower() != "true":
            continue
        return {
            "source_url": str(item.get("source_url") or ""),
            "published_on": str(item.get("published_on") or ""),
            "public_availability_bound_utc": bound_ts,
            "evidence_level": str(item.get("evidence_level") or "SECONDARY_INDEPENDENT_REFERENCE"),
            "claim_supported": str(item.get("claim_supported") or ""),
            "revision_sha": str(commit_sha),
        }
    return None


def stable_bleaguer_event_id(schedule_key: str) -> str:
    return hashlib.sha256(
        f"basketball|bleaguer|{schedule_key}".encode("utf-8")
    ).hexdigest()[:32]


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
            "event_provenance": [],
        }
    current_hash = sha256_bytes(current)
    commits = commit_history(s, path)
    event_targets = summary_targets_from_bytes(current) if "games_summary_" in path else {}
    remaining_events = set(event_targets)
    event_provenance: dict[str, dict[str, Any]] = {}

    # GitHub returns newest-first. Scan oldest-to-newest so the first matching
    # revision is the earliest public evidence. The exact row pair must coexist
    # in the same historical file revision; two independent row sightings are
    # never combined into one PIT claim.
    ordered_commits = sorted(
        commits,
        key=lambda c: iso(_commit_date(c) or "") or "9999-12-31T23:59:59+00:00",
    )
    matches: list[tuple[str, str]] = []
    for c in ordered_commits:
        sha = c.get("sha")
        commit_date = _commit_date(c)
        if not sha or not commit_date:
            continue
        try:
            b = get_bytes(s, pinned_raw_url(path, sha))
        except Exception:
            continue

        if remaining_events:
            matched = match_summary_revision(b, event_targets, remaining_events)
            for schedule_key in matched:
                bound = secondary_publication_bound(path, sha)
                event_provenance[schedule_key] = {
                    "schedule_key": schedule_key,
                    "provenance_commit_sha": sha,
                    "commit_timestamp_utc": iso(commit_date),
                    "publication_status": "PROVEN_BY_SECONDARY_DATE_BOUND" if bound else "UNPROVEN",
                    "public_availability_bound_utc": bound["public_availability_bound_utc"] if bound else None,
                    "publication_evidence": bound if bound else None,
                    "content_hash": sha256_bytes(b),
                    "matched_team_ids": sorted(event_targets[schedule_key]),
                    "pinned_source_url": pinned_raw_url(path, sha),
                }
                remaining_events.remove(schedule_key)

        if sha256_bytes(b) == current_hash:
            matches.append((sha, commit_date))

    result: dict[str, Any] = {
        "path": path,
        "status": "VERSION_EXACT_PUBLICATION_UNPROVEN" if matches else "UNVERIFIABLE",
        "current_hash": current_hash,
        "checked_at_utc": utcnow(),
        "commits_checked": len(commits),
        "event_provenance": list(event_provenance.values()),
        "event_provenance_unresolved": len(remaining_events),
    }
    if matches:
        earliest_sha, earliest_date = sorted(matches, key=lambda x: x[1])[0]
        bound = secondary_publication_bound(path, earliest_sha)
        result.update({
            "provenance_commit_sha": earliest_sha,
            "commit_timestamp_utc": iso(earliest_date),
            "repository": f"{OWNER}/{REPO}",
            "branch": BRANCH,
            "publication_status": "PROVEN_BY_SECONDARY_DATE_BOUND" if bound else "UNPROVEN",
            "public_availability_bound_utc": bound["public_availability_bound_utc"] if bound else None,
            "publication_evidence": bound if bound else None,
        })
    else:
        result["reason"] = "no historical GitHub commit with identical bytes was found"
    return result


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
    version_exact_paths = 0
    event_version_exact = 0
    try:
        for p in proofs:
            url = f"{RAW_BASE}/{p['path']}"
            if p["status"] == "VERSION_EXACT_PUBLICATION_UNPROVEN":
                version_exact_paths += 1
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
                        "commit_observed_at_utc": p["commit_timestamp_utc"],
                        "publication_status": "UNPROVEN",
                        "exact_current_blob": True,
                    })
                    con.execute(
                        "UPDATE source_snapshot SET source_available_at_utc=NULL, "
                        "availability_status='VERSION_EXACT_PUBLICATION_UNPROVEN', provenance_json=? WHERE snapshot_id=?",
                        (json.dumps(old, ensure_ascii=False), snapshot_id),
                    )
                    updated += 1

            # Event-level proof is intentionally stored behind a commit-pinned
            # source URL. Keep source_snapshot.event_time_utc NULL because
            # proven stats are later consumed as prior observations for
            # subsequent target events; pit_replay_builder already applies the
            # event-specific effective_at and source_available_at PIT filters.
            # A non-NULL event_time would hide these prior stats from later
            # target events because the source join is event-time scoped.
            for ep in p.get("event_provenance", []):
                event_id = stable_bleaguer_event_id(ep["schedule_key"])
                event_row = con.execute(
                    "SELECT event_time_utc FROM event WHERE event_id=? AND sport='basketball'",
                    (event_id,),
                ).fetchone()
                if not event_row or ep.get("publication_status") != "UNPROVEN" or not ep.get("pinned_source_url"):
                    continue
                current_summary_url = url
                cur = con.execute(
                    "SELECT COUNT(*) FROM match_stats "
                    "WHERE sport='basketball' AND event_id=? AND source='bleaguer-github' AND source_url=?",
                    (event_id, current_summary_url),
                ).fetchone()
                if not cur or int(cur[0]) <= 0:
                    continue

                snapshot_id = hashlib.sha256(
                    f"basketball|bleaguer-github|{ep['pinned_source_url']}|{ep['content_hash']}|{event_id}".encode("utf-8")
                ).hexdigest()[:32]
                provenance = {
                    "provenance_method": "github_event_exact_feature_rows_v1",
                    "repository": f"{OWNER}/{REPO}",
                    "branch": BRANCH,
                    "schedule_key": ep["schedule_key"],
                    "matched_team_ids": ep.get("matched_team_ids", []),
                    "commit_sha": ep["provenance_commit_sha"],
                    "commit_observed_at_utc": ep["commit_timestamp_utc"],
                    "publication_status": "UNPROVEN",
                    "exact_feature_rows_in_same_revision": True,
                    "source_url_pinned_to_commit": True,
                }
                con.execute(
                    """INSERT OR REPLACE INTO source_snapshot(
                           snapshot_id,sport,source,source_url,retrieved_at_utc,
                           source_available_at_utc,event_time_utc,content_hash,
                           payload_path,parser_version,availability_status,provenance_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        snapshot_id,
                        "basketball",
                        "bleaguer-github",
                        ep["pinned_source_url"],
                        p.get("checked_at_utc") or utcnow(),
                        None,
                        None,
                        ep["content_hash"],
                        None,
                        "bleaguer-git-provenance-v3-version-only",
                        "VERSION_EXACT_PUBLICATION_UNPROVEN",
                        json.dumps(provenance, ensure_ascii=False),
                    ),
                )
                event_version_exact += 1
                # Do not rewrite match_stats to an unproven historical URL.
                # Version provenance remains diagnostic only. The current-source
                # feature row stays untouched until independent public-availability
                # evidence upgrades a source_snapshot to TRUE EXACT.
        con.commit()
    finally:
        con.close()
    return {
        "version_provenance_paths": version_exact_paths,
        "snapshot_rows_updated": updated,
        "event_version_provenance": event_version_exact,
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
        "version": "github-version-provenance-v3-publication-unproven",
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
