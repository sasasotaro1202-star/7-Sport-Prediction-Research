from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
OWNER = "rush2pranav"
REPO = "valorant-pro-scene-tracker"
BRANCH = "main"
PATH = "data/results.csv"
SOURCE = "public-vlr-dataset"
SOURCE_URL = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{PATH}"
API = f"https://api.github.com/repos/{OWNER}/{REPO}/commits"
UA = "SevenSportResearchEngine/4.6-pit-provenance"


def utc():
    return datetime.now(timezone.utc).isoformat()


def get(s, url, params=None):
    last = None
    for attempt in range(5):
        try:
            r = s.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            last = exc
            if attempt < 4:
                time.sleep(1.5 * (2 ** attempt))
    raise last or RuntimeError("request failed")


def main():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/vnd.github+json"})
    current = get(s, SOURCE_URL).content
    digest = hashlib.sha256(current).hexdigest()

    commits = []
    for page in range(1, 11):
        rows = get(s, API, {"path": PATH, "per_page": 100, "page": page}).json()
        if not rows:
            break
        commits.extend(rows)
        if len(rows) < 100:
            break

    matches = []
    for row in commits:
        sha = row.get("sha")
        if not sha:
            continue
        try:
            blob = get(s, f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{sha}/{PATH}").content
        except Exception:
            continue
        if hashlib.sha256(blob).hexdigest() != digest:
            continue
        date = ((row.get("commit") or {}).get("committer") or {}).get("date")
        if date:
            matches.append((sha, date))

    con = sqlite3.connect(DB)
    result = {"source": SOURCE, "path": PATH, "checked_at_utc": utc(),
              "current_sha256": digest, "commits_checked": len(commits),
              "matching_commits": len(matches), "status": "UNVERIFIABLE",
              "updated_rows": 0}
    try:
        if matches:
            sha, observed = sorted(matches, key=lambda x: x[1])[0]
            available = datetime.fromisoformat(observed.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
            rows = con.execute(
                "SELECT snapshot_id, provenance_json FROM source_snapshot "
                "WHERE source=? AND source_url=?",
                (SOURCE, SOURCE_URL),
            ).fetchall()
            for snapshot_id, old_json in rows:
                try:
                    meta = json.loads(old_json or "{}")
                except Exception:
                    meta = {}
                meta.update({
                    "provenance_method": "github_commit_identical_blob",
                    "repository": f"{OWNER}/{REPO}",
                    "branch": BRANCH,
                    "commit_sha": sha,
                    "commit_observed_at_utc": available,
                    "exact_current_blob": True,
                })
                con.execute(
                    "UPDATE source_snapshot SET source_available_at_utc=?, "
                    "availability_status='EXACT', provenance_json=? WHERE snapshot_id=?",
                    (available, json.dumps(meta, ensure_ascii=False), snapshot_id),
                )
                result["updated_rows"] += 1
            con.commit()
            result.update({"status": "EXACT", "source_available_at_utc": available,
                           "provenance_commit_sha": sha})
    finally:
        con.close()

    out = ROOT / "results" / "valorant_git_provenance.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
