from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "cross_sport_source_probe"

SPORT_URLS = {
    "basketball": "https://www.sofascore.com/basketball",
    "volleyball": "https://www.sofascore.com/volleyball",
    "ufc": "https://www.sofascore.com/en-us/mma",
    "rizin": "https://www.sofascore.com/en-us/mma/organisation/rizin/19905",
    "valorant": "https://www.sofascore.com/esports",
    "tennis": "https://www.sofascore.com/tennis",
    "f1": "https://www.sofascore.com/motorsport",
    "rugby": "https://www.sofascore.com/rugby",
    "boxing": "https://www.sofascore.com/mma",
}


def probe(url: str) -> dict:
    started = time.monotonic()
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "NineSportResearchEngine/1.0",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(4096)
            return {
                "ok": 200 <= response.status < 400 and bool(body),
                "status_code": int(response.status),
                "bytes_sampled": len(body),
                "elapsed_sec": round(time.monotonic() - started, 3),
                "final_url": response.geturl(),
            }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "status_code": int(exc.code),
            "elapsed_sec": round(time.monotonic() - started, 3),
            "error": f"HTTPError:{exc.code}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "error": repr(exc),
        }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = {}
    for sport, url in SPORT_URLS.items():
        rows[sport] = {"url": url, **probe(url)}

    report = {
        "version": "cross-sport-source-probe-v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Sofascore public web pages",
        "research_only": True,
        "production_model_touched": False,
        "pit_status": "NOT_ESTABLISHED",
        "sports": rows,
        "healthy_count": sum(1 for row in rows.values() if row.get("ok")),
        "sport_count": len(rows),
    }
    (OUT / "sofascore.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["healthy_count"] == report["sport_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
