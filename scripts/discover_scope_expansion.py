from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "SCOPE_EXPANSION_FRONTIER.json"
DEFAULT_OUTPUT = ROOT / "results" / "scope_expansion" / "discovery.json"
ALLOWED_HOSTS = {"sports.core.api.espn.com", "site.api.espn.com"}
USER_AGENT = "7-Sport-Prediction-Research/scope-discovery-v1"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request_json(url: str, timeout: int = 12) -> tuple[dict | None, dict]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        return None, {"status": "BLOCKED_HOST", "url": url}
    last = None
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    return None, {"status": "INVALID_JSON_OBJECT", "http_status": int(resp.status)}
                return payload, {"status": "OK", "http_status": int(resp.status), "bytes": len(body)}
        except HTTPError as exc:
            last = exc
            if exc.code not in (408, 429) and not (500 <= exc.code < 600):
                break
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last = exc
        if attempt < 2:
            time.sleep(1.0 * (attempt + 1))
    return None, {"status": "REQUEST_FAILED", "error": repr(last)}


def _items(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    for key in ("items", "leagues"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def _league_summary(item: dict) -> dict:
    sport = item.get("sport")
    sport_slug = sport.get("slug") if isinstance(sport, dict) else None
    return {
        "id": item.get("id"),
        "uid": item.get("uid"),
        "slug": item.get("slug"),
        "name": item.get("name"),
        "abbreviation": item.get("abbreviation"),
        "isTournament": item.get("isTournament"),
        "sport": sport_slug,
    }


def _active_leagues(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    out = []
    for sport in payload.get("sports") or []:
        if not isinstance(sport, dict):
            continue
        for league in sport.get("leagues") or []:
            if not isinstance(league, dict):
                continue
            events = league.get("events") or []
            out.append({
                "id": league.get("id"),
                "name": league.get("name"),
                "slug": league.get("slug"),
                "event_count": len(events) if isinstance(events, list) else None,
            })
    return out


def discover_one(sport: str, slug: str) -> dict:
    started = utcnow()
    catalog_url = f"https://sports.core.api.espn.com/v2/sports/{slug}/leagues?limit=100"
    catalog, catalog_meta = _request_json(catalog_url)
    header_url = "https://site.api.espn.com/apis/personalized/v2/scoreboard/header?" + urlencode(
        {"sport": slug, "region": "us", "tz": "utc"}
    )
    active, active_meta = _request_json(header_url)
    leagues = [_league_summary(x) for x in _items(catalog)]
    active_rows = _active_leagues(active)
    return {
        "sport": sport,
        "espn_slug": slug,
        "retrieved_at_utc": started,
        "sources": {
            "league_catalog": {"url": catalog_url, **catalog_meta},
            "active_header": {"url": header_url, **active_meta},
        },
        "league_count": len(leagues),
        "leagues": leagues,
        "active_series": active_rows,
        "status": "DISCOVERED" if leagues or active_rows else "NO_DISCOVERY_EVIDENCE",
        "pit_status": "UNPROVEN",
        "research_only": True,
        "production_model_touched": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    candidates = [x for x in (cfg.get("expansion_candidates") or []) if isinstance(x, dict)]
    results = [discover_one(str(x["sport"]), str(x["espn_slug"])) for x in candidates]
    payload = {
        "version": "scope-discovery-v1",
        "generated_at_utc": utcnow(),
        "policy": cfg.get("policy") or {},
        "candidate_count": len(results),
        "results": results,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    counts = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(f"SCOPE_DISCOVERY candidate_count={len(results)} statuses={counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
