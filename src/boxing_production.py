from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "v45" / "boxing_coverage.json"

OPEN_BOXING_TREE = "https://api.github.com/repos/boxingundefeated/open-boxing-data/git/trees/main?recursive=1"

CANDIDATES = [
    {
        "name": "Boxing Undefeated / open-boxing-data",
        "url": "https://github.com/boxingundefeated/open-boxing-data",
        "role": "free/open historical data candidate",
        "pit_status": "UNPROVEN",
    },
    {
        "name": "BoxingScene",
        "url": "https://www.boxingscene.com/",
        "role": "public current schedule/results candidate",
        "pit_status": "UNPROVEN",
    },
    {
        "name": "BoxRec",
        "url": "https://boxrec.com/",
        "role": "public boxing record candidate; access/terms risk requires separate review",
        "pit_status": "UNPROVEN",
    },
]


def probe(url: str) -> dict:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (boxing-research-guard)"})
        with urlopen(req, timeout=12) as resp:
            data = resp.read(512)
            return {"reachable": True, "status": getattr(resp, "status", None), "bytes_probe": len(data)}
    except Exception as exc:
        return {"reachable": False, "error": type(exc).__name__}


def probe_machine_readable_tree() -> dict:
    try:
        req = Request(OPEN_BOXING_TREE, headers={"User-Agent": "boxing-research-guard", "Accept": "application/vnd.github+json"})
        with urlopen(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        files = [
            str(x.get("path")) for x in (payload.get("tree") or [])
            if x.get("type") == "blob" and str(x.get("path", "")).lower().endswith((".csv", ".json", ".jsonl", ".parquet", ".zip"))
        ]
        return {"reachable": True, "tree_sha": payload.get("sha"), "machine_readable_candidates": files[:100]}
    except Exception as exc:
        return {"reachable": False, "error": type(exc).__name__}

def main() -> int:
    checks = []
    for c in CANDIDATES:
        checks.append({**c, "probe": probe(c["url"])})

    checks.append({"name": "open-boxing-data machine-readable tree", "url": OPEN_BOXING_TREE, "role": "automatic discovery only; still requires historical PIT proof", "probe": probe_machine_readable_tree()})
    report = {
        "sport": "boxing",
        "status": "DEFERRED_PIT",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "prediction_cutoff_rule": "event_time_minus_60m",
        "provenance_rule": "retrieval time is never treated as historical publication availability",
        "production_model_enabled": False,
        "reason": "No free public boxing source currently proves historical source availability before the prediction cutoff. Candidate sources are monitored only; no unverifiable data enters training or future prediction.",
        "candidate_sources": checks,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
