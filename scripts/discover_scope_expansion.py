from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from src.competition_scope_classifier import classify_competition

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "SCOPE_EXPANSION_FRONTIER.json"
DEFAULT_OUTPUT = ROOT / "results" / "scope_expansion" / "discovery.json"
EXCLUDED_SPORTS = frozenset({"baseball", "soccer"})
ALLOWED_HOSTS = {
    "sports.core.api.espn.com",
    "site.api.espn.com",
    "api-web.nhle.com",
    "cricsheet.org",
    "api.snooker.org",
    "api.opendota.com",
    "api.openwec.com",
}
USER_AGENT = "7-Sport-Prediction-Research/scope-discovery-v2"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(url: str, timeout: int = 12) -> tuple[bytes | None, dict]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        return None, {"status": "BLOCKED_HOST", "url": url}
    last = None
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html;q=0.9,*/*;q=0.5"})
            with urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                return body, {"status": "OK", "http_status": int(resp.status), "bytes": len(body), "content_type": resp.headers.get("content-type")}
        except HTTPError as exc:
            last = exc
            if exc.code not in (408, 429) and not (500 <= exc.code < 600):
                break
        except (URLError, TimeoutError, OSError) as exc:
            last = exc
        if attempt < 2:
            time.sleep(1.0 * (attempt + 1))
    return None, {"status": "REQUEST_FAILED", "error": repr(last)}


def _request_json(url: str, timeout: int = 12) -> tuple[dict | None, dict]:
    body, meta = _request(url, timeout)
    if body is None:
        return None, meta
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, {**meta, "status": "INVALID_JSON", "error": repr(exc)}
    if not isinstance(payload, dict):
        return None, {**meta, "status": "INVALID_JSON_OBJECT"}
    return payload, meta


def _request_text(url: str, timeout: int = 12) -> tuple[str | None, dict]:
    body, meta = _request(url, timeout)
    if body is None:
        return None, meta
    return body.decode("utf-8", errors="replace"), meta


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
    name = item.get("name")
    return {"id": item.get("id"), "uid": item.get("uid"), "slug": item.get("slug"),
            "name": name, "abbreviation": item.get("abbreviation"),
            "isTournament": item.get("isTournament"), "sport": sport_slug,
            "classification": classify_competition(str(sport_slug or ""), name)}


def _active_leagues(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    out = []
    for sport in payload.get("sports") or []:
        if not isinstance(sport, dict):
            continue
        sport_slug = sport.get("slug") or sport.get("sport")
        for league in sport.get("leagues") or []:
            if not isinstance(league, dict):
                continue
            events = league.get("events") or []
            name = league.get("name")
            out.append({"id": league.get("id"), "name": name, "slug": league.get("slug"),
                        "sport": sport_slug,
                        "event_count": len(events) if isinstance(events, list) else None,
                        "classification": classify_competition(str(sport_slug or ""), name)})
    return out


def discover_espn(sport: str, slug: str) -> dict:
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
        "sport": sport, "provider": "espn", "espn_slug": slug, "retrieved_at_utc": started,
        "sources": {"league_catalog": {"url": catalog_url, **catalog_meta}, "active_header": {"url": header_url, **active_meta}},
        "league_count": len(leagues), "leagues": leagues, "active_series": active_rows,
        "status": "DISCOVERED" if leagues or active_rows else "NO_DISCOVERY_EVIDENCE",
        "pit_status": "UNPROVEN", "research_only": True, "production_model_touched": False,
    }


def discover_nhl(sport: str) -> dict:
    started = utcnow()
    urls = {"schedule": "https://api-web.nhle.com/v1/schedule/now", "scoreboard": "https://api-web.nhle.com/v1/scoreboard/now"}
    payloads = {}
    metas = {}
    for key, url in urls.items():
        payloads[key], metas[key] = _request_json(url)
    games = []
    for payload in payloads.values():
        if isinstance(payload, dict):
            games.extend(x for x in (payload.get("games") or []) if isinstance(x, dict))
    ids = sorted({str(g.get("id")) for g in games if g.get("id") is not None})
    return {
        "sport": sport, "provider": "nhl_official", "retrieved_at_utc": started,
        "sources": {k: {"url": urls[k], **metas[k]} for k in urls},
        "game_count": len(ids), "sample_game_ids": ids[:10],
        "status": "DISCOVERED" if ids else "NO_DISCOVERY_EVIDENCE",
        "pit_status": "UNPROVEN", "research_only": True, "production_model_touched": False,
    }


def discover_cricsheet(sport: str) -> dict:
    started = utcnow()
    url = "https://cricsheet.org/downloads/"
    page, meta = _request_text(url)
    links = sorted(set(re.findall(r'href=["\']([^"\']+\.zip)["\']', page or "", re.IGNORECASE)))
    marker_text = (page or "").lower()
    markers = {"has_json": "json" in marker_text, "has_ball_by_ball": "ball-by-ball" in marker_text, "zip_count": len(links)}
    return {
        "sport": sport, "provider": "cricsheet", "retrieved_at_utc": started,
        "sources": {"downloads_page": {"url": url, **meta}},
        "download_zip_count": len(links), "download_examples": links[:15],
        "format_markers": markers,
        "status": "DISCOVERED" if markers["has_json"] and links else "NO_DISCOVERY_EVIDENCE",
        "pit_status": "UNPROVEN", "research_only": True, "production_model_touched": False,
    }


def discover_opendota(sport: str) -> dict:
    started = utcnow()
    urls = {
        "status": "https://api.opendota.com/api/status",
        "public_matches": "https://api.opendota.com/api/publicMatches?less_than=9999999999",
    }
    payloads = {}
    metas = {}
    for key, url in urls.items():
        payloads[key], metas[key] = _request_json(url)
    rows = payloads.get("public_matches")
    rows = rows if isinstance(rows, list) else []
    return {
        "sport": sport, "provider": "opendota", "retrieved_at_utc": started,
        "sources": {k: {"url": urls[k], **metas[k]} for k in urls},
        "public_match_sample_count": len(rows),
        "status": "DISCOVERED" if rows else "NO_DISCOVERY_EVIDENCE",
        "pit_status": "UNPROVEN", "research_only": True, "production_model_touched": False,
    }


def discover_openwec(sport: str) -> dict:
    started = utcnow()
    urls = {
        "series": "https://api.openwec.com/api/v1/series",
        "events": "https://api.openwec.com/api/v1/series/WEC/seasons/2026/events",
    }
    payloads = {}
    metas = {}
    for key, url in urls.items():
        payloads[key], metas[key] = _request_json(url)
    series = payloads.get("series")
    events = payloads.get("events")
    series_rows = series.get("data") if isinstance(series, dict) else None
    event_rows = events.get("data") if isinstance(events, dict) else None
    series_count = len(series_rows) if isinstance(series_rows, list) else 0
    event_count = len(event_rows) if isinstance(event_rows, list) else 0
    return {
        "sport": sport, "provider": "openwec", "retrieved_at_utc": started,
        "sources": {k: {"url": urls[k], **metas[k]} for k in urls},
        "series_count": series_count, "event_count": event_count,
        "status": "DISCOVERED" if series_count or event_count else "NO_DISCOVERY_EVIDENCE",
        "pit_status": "UNPROVEN", "research_only": True, "production_model_touched": False,
    }


def discover_snooker(sport: str) -> dict:
    started = utcnow()
    url = "https://api.snooker.org/"
    page, meta = _request_text(url)
    requires_header = "X-Requested-By" in (page or "")
    return {
        "sport": sport, "provider": "snooker_org", "retrieved_at_utc": started,
        "sources": {"api_root": {"url": url, **meta}},
        "status": "ACCESS_APPROVAL_REQUIRED" if requires_header else ("DISCOVERED" if page else "NO_DISCOVERY_EVIDENCE"),
        "pit_status": "UNPROVEN", "research_only": True, "production_model_touched": False,
    }


def discover_reference(item: dict) -> dict:
    return {"sport": str(item.get("sport")), "provider": str(item.get("provider")),
            "retrieved_at_utc": utcnow(), "reference_url": item.get("reference_url"),
            "status": "REFERENCE_CANDIDATE", "pit_status": "UNPROVEN",
            "research_only": True, "production_model_touched": False}


def discover_candidate(item: dict) -> dict:
    sport = str(item.get("sport"))
    if sport in EXCLUDED_SPORTS:
        return {
            "sport": sport,
            "provider": str(item.get("provider") or "unknown"),
            "retrieved_at_utc": utcnow(),
            "status": "EXCLUDED_SPORT",
            "pit_status": "UNPROVEN",
            "research_only": True,
            "production_model_touched": False,
        }
    provider = str(item.get("provider") or "espn")
    if provider == "espn":
        slug = item.get("espn_slug")
        if not slug:
            return {"sport": sport, "provider": provider, "status": "MISSING_PROVIDER_PARAMETERS",
                    "pit_status": "UNPROVEN", "research_only": True, "production_model_touched": False}
        return discover_espn(sport, str(slug))
    if provider == "nhl_official":
        return discover_nhl(sport)
    if provider == "cricsheet":
        return discover_cricsheet(sport)
    if provider == "opendota":
        return discover_opendota(sport)
    if provider == "openwec":
        return discover_openwec(sport)
    if provider == "snooker_org":
        return discover_snooker(sport)
    return discover_reference(item)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    excluded = {str(x) for x in (cfg.get("excluded_sports") or [])} | EXCLUDED_SPORTS
    candidates = [x for x in (cfg.get("expansion_candidates") or []) if isinstance(x, dict) and str(x.get("sport")) not in excluded]
    source_candidates = [x for x in (cfg.get("source_probe_candidates") or []) if isinstance(x, dict) and str(x.get("sport")) not in excluded]
    results = [discover_candidate(x) for x in candidates]
    source_results = [discover_candidate(x) for x in source_candidates]
    payload = {
        "version": "scope-discovery-v2", "generated_at_utc": utcnow(),
        "policy": cfg.get("policy") or {}, "excluded_sports": sorted(excluded),
        "candidate_count": len(results), "source_probe_candidate_count": len(source_results),
        "results": results, "source_probe_results": source_results,
    }
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    counts={}
    for row in results+source_results:
        counts[row["status"]]=counts.get(row["status"],0)+1
    print(f"SCOPE_DISCOVERY candidate_count={len(results)} source_probe_candidate_count={len(source_results)} statuses={counts}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
