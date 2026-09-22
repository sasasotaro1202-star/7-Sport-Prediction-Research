from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "v45" / "boxing_coverage.json"

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


def main() -> int:
    checks = []
    for c in CANDIDATES:
        checks.append({**c, "probe": probe(c["url"])})

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
