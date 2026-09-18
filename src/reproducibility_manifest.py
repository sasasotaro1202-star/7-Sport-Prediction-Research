from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/sports_v45.sqlite"
SPORTS = ("valorant", "basketball", "volleyball", "tennis", "ufc", "rizin", "f1", "rugby")
OUT = ROOT / "results/reproducibility_manifest.json"


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


def file_record(path: Path) -> dict:
    if not path.is_file():
        return {"path": str(path.relative_to(ROOT)), "exists": False}
    return {
        "path": str(path.relative_to(ROOT)),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def db_counts() -> dict:
    import sqlite3

    if not DB.is_file() or DB.stat().st_size == 0:
        return {}
    con = sqlite3.connect(f"file:{DB.resolve()}?mode=ro", uri=True)
    try:
        return dict(con.execute("SELECT sport, COUNT(*) FROM event GROUP BY sport").fetchall())
    finally:
        con.close()


def main() -> int:
    requirements = ROOT / "requirements.txt"
    tracked = [
        DB,
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

    manifest = {
        "manifest_version": "repro-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_git_commit_sha": git_head(),
        "requirements_sha256": sha256_file(requirements) if requirements.is_file() else None,
        "sports": list(SPORTS),
        "event_counts": {s: int(db_counts().get(s, 0)) for s in SPORTS},
        "files": files,
        "policy": {
            "manifest_excludes_self": True,
            "hashes_are_sha256": True,
            "missing_files_are_explicit": True,
            "models_are_artifacts_only_after_release_gate": True,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
