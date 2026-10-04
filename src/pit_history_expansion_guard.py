from __future__ import annotations

"""Fail closed when a declared strict-PIT provenance bridge has no applied effect."""

import argparse
import json
import sqlite3
from pathlib import Path

EXPECTED = {
    "basketball": {
        "source": "bleaguer-github",
        "path": "inst/extdata/games_summary_202021.csv",
        "revision_key": "revision_evidence",
    }
}
PUBLIC_MARKER = "PROVEN_BY_SECONDARY_DATE_BOUND"


def _load_registry(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"evidence_registry_unreadable:{type(exc).__name__}") from exc
    if not isinstance(obj, dict):
        raise RuntimeError("evidence_registry_wrong_shape")
    if obj.get("status") != "RESEARCH_EVIDENCE_ONLY":
        raise RuntimeError(f"evidence_registry_unsafe_status:{obj.get('status')}")
    if obj.get("strict_pit_usable") is not False:
        raise RuntimeError("evidence_registry_strict_pit_flag_not_fail_closed")
    return obj


def inspect_bridge(db: Path, sport: str, evidence_path: Path) -> dict:
    expected = EXPECTED.get(sport)
    if expected is None:
        return {"status": "PASS", "sport": sport, "reason": "no_explicit_bridge_expectation"}

    registry = _load_registry(evidence_path)
    revision = registry.get(expected["revision_key"]) or {}
    revision_sha = str(revision.get("revision_sha") or revision.get("exact_revision_sha") or "")
    bound = ((revision.get("public_availability_bound") or {}).get("latest_safe_utc"))
    if not revision_sha or not bound:
        raise RuntimeError("evidence_registry_exact_revision_or_bound_missing")
    if expected["path"] != str(revision.get("file") or expected["path"]):
        raise RuntimeError("evidence_registry_path_mismatch")

    with sqlite3.connect(db) as con:
        exact_master = int(con.execute(
            """SELECT COUNT(*)
                 FROM source_snapshot
                WHERE sport=?
                  AND source=?
                  AND source_url LIKE ?
                  AND availability_status='EXACT'
                  AND source_available_at_utc IS NOT NULL
                  AND provenance_json LIKE ?""",
            (
                sport,
                expected["source"],
                f"%{expected['path']}",
                f"%{PUBLIC_MARKER}%",
            ),
        ).fetchone()[0])
        pinned_exact = int(con.execute(
            """SELECT COUNT(*)
                 FROM source_snapshot
                WHERE sport=?
                  AND source=?
                  AND source_url LIKE ?
                  AND availability_status='EXACT'
                  AND source_available_at_utc=?
                  AND provenance_json LIKE ?""",
            (
                sport,
                expected["source"],
                f"%/{revision_sha}/{expected['path']}",
                bound.replace("Z", "+00:00"),
                f"%{PUBLIC_MARKER}%",
            ),
        ).fetchone()[0])
        repointed_stats = int(con.execute(
            """SELECT COUNT(*)
                 FROM match_stats
                WHERE sport=?
                  AND source=?
                  AND source_url LIKE ?""",
            (
                sport,
                expected["source"],
                f"%/{revision_sha}/{expected['path']}",
            ),
        ).fetchone()[0])

    result = {
        "status": "PASS" if pinned_exact > 0 and repointed_stats > 0 else "BLOCKED",
        "sport": sport,
        "required": {
            "source": expected["source"],
            "path": expected["path"],
            "revision_sha": revision_sha,
            "public_availability_bound_utc": bound,
        },
        "observed": {
            "exact_master_summary_snapshots": exact_master,
            "pinned_exact_summary_snapshots": pinned_exact,
            "repointed_summary_match_stats": repointed_stats,
        },
        "reason": (
            "publication-bound provenance was applied to a commit-pinned snapshot and connected to match_stats"
            if pinned_exact > 0 and repointed_stats > 0
            else "declared publication-bound bridge exists but the current PIT database shows no complete applied effect"
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/db/sports_v45.sqlite")
    ap.add_argument("--sport", required=True)
    ap.add_argument(
        "--evidence",
        default="results/research/bleague_public_availability_evidence.json",
    )
    args = ap.parse_args()

    try:
        result = inspect_bridge(Path(args.db), args.sport, Path(args.evidence))
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "sport": args.sport,
            "reason": str(exc),
        }, ensure_ascii=False, indent=2))
        return 1
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
