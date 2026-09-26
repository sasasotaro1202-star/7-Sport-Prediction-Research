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
        "basketball": "https://api.sofascore.com/api/v1/sport/basketball/scheduled-events/2026-09-27",
        "volleyball": "https://api.sofascore.com/api/v1/sport/volleyball/scheduled-events/2026-09-27",
        "ufc": "https://api.sofascore.com/api/v1/sport/mma/scheduled-events/2026-09-27",
        "rizin": "https://api.sofascore.com/api/v1/sport/mma/scheduled-events/2026-09-27",
        "valorant": "https://api.sofascore.com/api/v1/sport/esports/scheduled-events/2026-09-27",
        "tennis": "https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/2026-09-27",
        "f1": "https://api.sofascore.com/api/v1/sport/motorsport/scheduled-events/2026-09-27",
        "rugby": "https://api.sofascore.com/api/v1/sport/rugby/scheduled-events/2026-09-27",
        "boxing": "https://api.sofascore.com/api/v1/sport/mma/scheduled-events/2026-09-27",
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
        "ufc": "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
    },

    "f1api_dev": {
        "f1_current": "https://f1api.dev/api/current",
        "f1_drivers": "https://f1api.dev/api/drivers?limit=1"
    },
    "racehooks": {
        "f1_seasons": "https://api.racehooks.io/v1/historical/seasons"
    },
    "openboxing": {
        "boxing_bouts": "https://www.openboxing.org/api/bouts/all.json"
    },
    "ufc_stats_api_public_impl": {
        "completed_events": "https://www.ufcstats.com/statistics/events/completed?page=all"
    },
    "rizin_club": {
        "event_history": "https://rizin.club/"
    },
    "sx_bet": {
        "sports": "https://api.sx.bet/sports",
        "markets": "https://api.sx.bet/markets?limit=1"
    },
    "statbunker_rugby": {
        "rugby_home": "https://rugby.statbunker.com/"
    },
    "wta_official": {
        "wta_rankings": "https://api.wtatennis.com/tennis/players/ranked?type=rankSingles&metric=singles&pageSize=1"
    },
    "euroleague_official": {
        "euroleague_seasons": "https://api-live.euroleague.net/v2/seasons/E"
    },
    "tracinginsights_f1": {
        "telemetry_2026": "https://raw.githubusercontent.com/TracingInsights/2026/main/README.md"
    },
    "sporting_events_free": {
        "fixture_index": "https://sporting-events.org/data/"
    }
}

REQUIRED_SOURCES = {
    "thesportsdb",
    "espn",
    "rizin_club",
    "f1api_dev",
    "racehooks",
    "openboxing",
}

def probe(url: str) -> dict:
    started = time.monotonic()
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "NineSportResearchEngine/1.2",
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(16384)
            result = {
                "ok": 200 <= response.status < 400 and bool(body),
                "status_code": int(response.status),
                "bytes_sampled": len(body),
                "elapsed_sec": round(time.monotonic() - started, 3),
                "final_url": response.geturl(),
            }
            try:
                payload = json.loads(body.decode("utf-8"))
                result["json_parseable"] = True
                result["body_shape"] = type(payload).__name__
                if payload in ({}, [], None):
                    result["error_signal"] = "empty_json_payload"
                    result["ok"] = False
                elif isinstance(payload, dict):
                    errors = payload.get("errors")
                    if errors not in (None, {}, [], ""):
                        result["error_signal"] = "json_errors"
                        result["ok"] = False
                    elif payload.get("error") not in (None, {}, [], ""):
                        result["error_signal"] = "json_error"
                        result["ok"] = False
                    elif str(payload.get("status", "")).lower() in {"failure", "failed", "error"}:
                        result["error_signal"] = "json_failure_status"
                        result["ok"] = False
                    elif str(payload.get("message", "")).lower() in {"invalid api key", "application not found"}:
                        result["error_signal"] = "json_failure_message"
                        result["ok"] = False
            except (UnicodeDecodeError, json.JSONDecodeError):
                result["json_parseable"] = False
            return result
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
    required_failures = [name for name in REQUIRED_SOURCES if report["sources"].get(name, {}).get("healthy_count", 0) == 0]
    optional_failures = [name for name, data in report["sources"].items() if name not in REQUIRED_SOURCES and data.get("healthy_count", 0) == 0]
    report["required_zero_healthy"] = required_failures
    report["optional_zero_healthy"] = optional_failures
    healthy = not required_failures
    report["overall_status"] = "PASS" if healthy else "PARTIAL_FAILURE"
    (OUT / "cross_sport.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if optional_failures:
        print("CROSS_SPORT_OPTIONAL_ZERO_HEALTHY=" + ",".join(sorted(optional_failures)), flush=True)
    if not healthy:
        print("CROSS_SPORT_PROBE_RESULT=PARTIAL_FAILURE", flush=True)
        return 2
    print("CROSS_SPORT_PROBE_RESULT=PASS", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
