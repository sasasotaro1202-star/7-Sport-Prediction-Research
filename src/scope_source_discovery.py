from __future__ import annotations

import json
import os
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/SOURCE_REGISTRY_8_SPORTS.md"
OUT = ROOT / "results/scope_source_discovery.json"

UA = "SevenSportResearchScopeDiscovery/1.0"
TIMEOUT = int(os.getenv("SCOPE_DISCOVERY_TIMEOUT", "15"))

SPORT_QUERIES = {
    "basketball": ["B.LEAGUE data", "Asian Games basketball data", "basketball historical statistics"],
    "volleyball": ["Asian Games volleyball data", "FIVB volleyball historical statistics", "volleyball match data"],
    "ufc": ["UFC fight data historical", "UFC statistics dataset"],
    "rizin": ["RIZIN fight data historical", "RIZIN results dataset"],
    "valorant": ["VCT VALORANT data historical", "VALORANT match dataset"],
    "tennis": ["ATP WTA tennis historical data", "tennis match statistics dataset"],
    "f1": ["Formula 1 historical results data", "F1 timing dataset"],
    "rugby": ["rugby historical match data", "World Rugby statistics dataset"],
    "boxing": ["boxing historical results data", "boxing match dataset"],
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _urls_from_registry() -> list[str]:
    if not REGISTRY.is_file():
        return []
    text = REGISTRY.read_text(encoding="utf-8", errors="ignore")
    urls = sorted(set(re.findall(r"https?://[^\s)]+", text)))
    return urls


def _url_health(url: str) -> dict:
    try:
        r = requests.get(
            url,
            headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8,ja;q=0.6"},
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        return {
            "url": url,
            "status_code": int(r.status_code),
            "reachable": bool(r.ok),
            "final_url": str(r.url),
            "content_type": str(r.headers.get("content-type") or ""),
        }
    except Exception as exc:
        return {"url": url, "reachable": False, "error": repr(exc)}


def _github_code_leads() -> list[dict]:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    out: list[dict] = []
    for sport, queries in SPORT_QUERIES.items():
        query = queries[0]
        try:
            r = requests.get(
                "https://api.github.com/search/code",
                headers=headers,
                params={"q": f"{query} filename:csv", "per_page": 5},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            for item in (r.json().get("items") or []):
                out.append({
                    "sport": sport,
                    "query": query,
                    "name": item.get("name"),
                    "path": item.get("path"),
                    "repository": ((item.get("repository") or {}).get("full_name")),
                    "html_url": item.get("html_url"),
                })
        except Exception as exc:
            out.append({
                "sport": sport,
                "query": query,
                "status": "CODE_SEARCH_FAILED",
                "error": repr(exc),
            })
    return out


def _github_repo_leads() -> list[dict]:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": UA,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    out: list[dict] = []
    for sport, queries in SPORT_QUERIES.items():
        for query in queries:
            try:
                r = requests.get(
                    "https://api.github.com/search/repositories",
                    headers=headers,
                    params={"q": query, "sort": "updated", "order": "desc", "per_page": 8},
                    timeout=TIMEOUT,
                )
                r.raise_for_status()
                items = r.json().get("items") or []
                for item in items:
                    out.append({
                        "sport": sport,
                        "query": query,
                        "full_name": item.get("full_name"),
                        "html_url": item.get("html_url"),
                        "description": item.get("description"),
                        "updated_at": item.get("updated_at"),
                        "fork": bool(item.get("fork")),
                    })
            except Exception as exc:
                out.append({"sport": sport, "query": query, "status": "SEARCH_FAILED", "error": repr(exc)})
    return out


def main() -> int:
    urls = _urls_from_registry()
    health = [_url_health(url) for url in urls]
    leads = _github_repo_leads()

    # Discovery is evidence collection, not adoption. A GitHub repository,
    # reachable URL, or search hit never enters a prediction feature/model by itself.
    github_failures = sum(1 for x in leads if str(x.get("status", "")).endswith("_FAILED"))
    code_failures = sum(1 for x in code_leads if str(x.get("status", "")).endswith("_FAILED"))
    total_registry = len(health)
    reachable_registry = sum(1 for x in health if x.get("reachable"))
    total_queries = len(SPORT_QUERIES)
    status = "EVALUATED"
    if github_failures >= total_queries and code_failures >= total_queries and reachable_registry == 0 and total_registry > 0:
        status = "FAILED"
    elif github_failures or code_failures or reachable_registry < total_registry:
        status = "DEGRADED"

    report = {
        "version": "scope-source-discovery-v1",
        "status": status,
        "checked_at_utc": _utc(),
        "free_only": True,
        "registry_urls_checked": len(urls),
        "reachable_registry_urls": reachable_registry,
        "github_repo_leads": leads,
        "github_code_leads": code_leads,
        "per_sport": per_sport,
        "rules": {
            "retrieval_is_not_historical_pit": True,
            "discovery_does_not_adopt": True,
            "commercial_sources_require_explicit_review": True,
            "mirrors_and_republishers_do_not_count_as_independent": True,
        },
        "registry_health": health,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status != "FAILED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
