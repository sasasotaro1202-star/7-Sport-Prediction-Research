from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "cross_sport_source_probe"

PROBES = {
    "sofascore": {
        "basketball": "https://www.sofascore.com/basketball",
        "volleyball": "https://www.sofascore.com/volleyball",
        "ufc": "https://www.sofascore.com/en-us/mma",
        "rizin": "https://www.sofascore.com/en-us/mma/organisation/rizin/19905",
        "valorant": "https://www.sofascore.com/esports",
        "tennis": "https://www.sofascore.com/tennis",
        "f1": "https://www.sofascore.com/motorsport",
        "rugby": "https://www.sofascore.com/rugby",
        "boxing": "https://www.sofascore.com/mma",
    },
    "thesportsdb": {
        "basketball": "https://www.thesportsdb.com/api/v1/json/123/search_all_leagues.php?s=Basketball",
        "volleyball": "https://www.thesportsdb.com/api/v1/json/123/search_all_leagues.php?s=Volleyball",
        "ufc": "https://www.thesportsdb.com/api/v1/json/123/search_all_leagues.php?s=Fighting",
        "rizin": "https://www.thesportsdb.com/api/v1/json/123/search_all_leagues.php?s=Rizin",
        "valorant": "https://www.thesportsdb.com/api/v1/json/123/search_all_leagues.php?s=Valorant",
        "tennis": "https://www.thesportsdb.com/api/v1/json/123/search_all_leagues.php?s=Tennis",
        "f1": "https://www.thesportsdb.com/api/v1/json/123/search_all_leagues.php?s=Motorsport",
        "rugby": "https://www.thesportsdb.com/api/v1/json/123/search_all_leagues.php?s=Rugby",
        "boxing": "https://www.thesportsdb.com/api/v1/json/123/search_all_leagues.php?s=Boxing",
    },
    "espn": {
        "basketball": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
        "volleyball": "https://site.api.espn.com/apis/site/v2/sports/volleyball/fivb.w/scoreboard",
        "ufc": "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard",
        "tennis": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
        "f1": "https://site.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard",
        "rugby": "https://site.api.espn.com/apis/site/v2/sports/rugby/164205/scoreboard",
    },
}

def probe(url: str) -> dict:
    started = time.monotonic()
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "NineSportResearchEngine/1.1",
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(8192)
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
    report = {
        "version": "cross-sport-source-probe-v2",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_model_touched": False,
        "pit_status": "NOT_ESTABLISHED",
        "sources": {},
    }
    for source, sports in PROBES.items():
        rows = {sport: {"url": url, **probe(url)} for sport, url in sports.items()}
        report["sources"][source] = {
            "results": rows,
            "healthy_count": sum(1 for row in rows.values() if row.get("ok")),
            "probe_count": len(rows),
        }

    (OUT / "cross_sport.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # The probe itself is diagnostic. Source outage must be visible but must not
    # be converted into a false-success CI result.
    return 0 if all(source_data["healthy_count"] > 0 for source_data in report["sources"].values()) else 2

if __name__ == "__main__":
    raise SystemExit(main())
