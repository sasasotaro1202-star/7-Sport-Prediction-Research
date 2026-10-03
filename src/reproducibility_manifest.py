from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
RUGBY_DB = ROOT / "data/db/rugby_v45.sqlite"
BOXING_DB = ROOT / "data/db/boxing_v45.sqlite"
SPORTS = ("valorant", "basketball", "volleyball", "tennis", "ufc", "rizin", "f1", "rugby", "boxing")
OUT = ROOT / "results/reproducibility_manifest.json"


def display_path(path: Path) -> str:
    """Return a stable relative path for repo files, absolute path otherwise."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head() -> str:
    p = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    )
    return p.stdout.strip()


def display_path(path: Path) -> str:
    """Return a stable relative path for repo files and a safe absolute fallback for test fixtures."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def file_record(path: Path) -> dict:
    if not path.is_file():
        return {"path": display_path(path), "exists": False}
    return {
        "path": display_path(path),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _count_events(path: Path, sport: str | None = None) -> tuple[int, str]:
    import sqlite3

    if not path.is_file() or path.stat().st_size <= 0:
        return 0, "MISSING"
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event'"
        ).fetchone()
        if not table:
            return 0, "SCHEMA_MISSING"
        if sport is None:
            return int(con.execute("SELECT COUNT(*) FROM event").fetchone()[0]), "OK"
        row = con.execute("SELECT COUNT(*) FROM event WHERE sport=?", (sport,)).fetchone()
        return int(row[0]) if row else 0, "OK"
    finally:
        con.close()


def db_counts() -> tuple[dict, dict]:
    counts = {}
    storage = {}

    count, status = _count_events(DB)
    storage["canonical"] = {"path": display_path(DB), "status": status}
    if status == "OK":
        import sqlite3
        con = sqlite3.connect(f"file:{DB.resolve()}?mode=ro", uri=True)
        try:
            counts.update(
                dict(con.execute("SELECT sport, COUNT(*) FROM event GROUP BY sport").fetchall())
            )
        finally:
            con.close()

    for label, path, sport in (
        ("rugby", RUGBY_DB, "rugby"),
        ("boxing", BOXING_DB, "boxing"),
    ):
        count, status = _count_events(path, sport)
        storage[label] = {"path": display_path(path), "status": status}
        if status == "OK":
            counts[sport] = count

    return counts, storage


def main() -> int:
    requirements = ROOT / "requirements.txt"
    tracked = [
        DB,
        RUGBY_DB,
        BOXING_DB,
        ROOT / "results/quality_gate.json",
        ROOT / "results/release_gate.json",
        ROOT / "results/pit_replay.json",
        ROOT / "results/leakage_audit.json",
        ROOT / "results/research",
    ]
    models = sorted((ROOT / "models/research").glob("*")) if (ROOT / "models/research").is_dir() else []

    files = []
    for p in tracked:
        if p.is_file():
            files.append(file_record(p))
        elif p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file():
                    files.append(file_record(child))
        else:
            files.append(file_record(p))
    files.extend(file_record(p) for p in models)

    event_counts, storage_status = db_counts()

    manifest = {
        "manifest_version": "repro-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_git_commit_sha": git_head(),
        "requirements_sha256": sha256_file(requirements) if requirements.is_file() else None,
        "sports": list(SPORTS),
        "event_counts": {s: int(event_counts.get(s, 0)) for s in SPORTS},
        "storage_status": storage_status,
        "files": files,
        "policy": {
            "manifest_excludes_self": True,
            "hashes_are_sha256": True,
            "missing_files_are_explicit": True,
            "models_are_artifacts_only_after_release_gate": True,
            "rugby_uses_dedicated_database": True,
            "boxing_uses_dedicated_database": True,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
