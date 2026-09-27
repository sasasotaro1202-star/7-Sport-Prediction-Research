from __future__ import annotations

import argparse
import ast
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "SPORT_DATA_SOURCES_9.json"
POLICY_FILE = ROOT / "src" / "research_cycle_v4.py"
DB = ROOT / "data" / "db" / "sports_v45.sqlite"
RESULTS = ROOT / "results" / "source_usage"
SHADOW = ROOT / "results" / "cross_sport_shadow" / "shadow_sources.json"
SPORTS = ("valorant", "basketball", "volleyball", "tennis", "ufc", "rizin", "f1", "rugby", "boxing")

# These are collector entry points currently present in the repository.
# Presence here is intentionally NOT treated as model usage.
COLLECTORS = {
    "valorant": ["src.public_history_backfill", "src.valorant_git_provenance"],
    "basketball": ["src.basketball_cdn_backfill", "src.seven_sport_production.collect_espn"],
    "volleyball": ["src.volleyball_fivb_vis_backfill"],
    "tennis": ["src.tennis_public_backfill", "src.seven_sport_production.collect_wta_public"],
    "ufc": ["src.ufc_api_backfill"],
    "rizin": ["src.public_history_backfill"],
    "f1": ["src.f1_openf1_backfill", "src.seven_sport_production.collect_f1"],
    "rugby": ["src.rugby_production"],
    "boxing": ["src.boxing_production"],
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _load_policy(path: Path) -> dict[str, list[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "POLICY":
                    raw = ast.literal_eval(node.value)
                    return {str(k): [str(x) for x in v] for k, v in raw.items()}
    raise RuntimeError("POLICY assignment not found")


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower() or None
    except Exception:
        return None


def _registry_references(registry: dict) -> dict[str, list[str]]:
    out = {}
    for source_id, item in (registry.get("evidence") or {}).items():
        refs = item.get("references") or []
        hosts = []
        for ref in refs:
            host = _host(str(ref))
            if host:
                hosts.append(host[4:] if host.startswith("www.") else host)
        out[source_id] = sorted(set(hosts))
    return out


def _load_shadow(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_error": f"invalid_shadow_manifest:{exc}"}
    return raw if isinstance(raw, dict) else {"_error": "shadow_manifest_not_object"}


SOURCE_ALIASES = {
    "espn_public": {"espn"},
    "f1api_dev": {"f1api", "f1api_dev"},
    "wta_official": {"wta", "wta_official"},
    "euroleague_official": {"euroleague", "euroleague_official"},
    "openboxing": {"openboxing", "open-boxing"},
    "rizin_club": {"rizin.club", "rizin_club"},
    "world_rugby_official_archive": {"world.rugby", "world_rugby_official_archive"},
}

def _source_registry_match(source: str | None, url: str | None, refs: dict[str, list[str]]) -> list[str]:
    src = (source or "").lower()
    host = _host(url)
    matched = []
    for source_id, hosts in refs.items():
        aliases = SOURCE_ALIASES.get(source_id, set())
        if source_id.lower() == src or src in aliases:
            matched.append(source_id)
            continue
        # GitHub is intentionally excluded from host matching because many
        # unrelated registry candidates share github.com as a repository host.
        if host and host != "github.com" and any(host == h or host.endswith("." + h) for h in hosts):
            matched.append(source_id)
    return sorted(set(matched))


def _query_db(db_path: Path, sport: str, policy: dict[str, list[str]]) -> dict:
    if not db_path.exists():
        return {
            "db_present": False,
            "events": 0,
            "verified_outcomes": 0,
            "exact_snapshots": 0,
            "match_stat_rows": 0,
            "pit_usable_stat_rows": 0,
            "sources": [],
            "feature_usage": [],
        }

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        events = con.execute("SELECT COUNT(*) FROM event WHERE sport=?", (sport,)).fetchone()[0]
        outcomes = con.execute(
            "SELECT COUNT(*) FROM event_outcome WHERE sport=? AND outcome_status='VERIFIED'",
            (sport,),
        ).fetchone()[0]
        exact = con.execute(
            "SELECT COUNT(*) FROM source_snapshot "
            "WHERE sport=? AND availability_status='EXACT' "
            "AND source_available_at_utc IS NOT NULL",
            (sport,),
        ).fetchone()[0]
        stat_rows = con.execute(
            "SELECT COUNT(*) FROM match_stats WHERE sport=? AND value_num IS NOT NULL",
            (sport,),
        ).fetchone()[0]

        rows = con.execute(
            """SELECT
                 ms.source, ms.source_url, ms.stat_name,
                 COUNT(*) AS rows_count,
                 COUNT(DISTINCT ms.event_id) AS event_count,
                 SUM(CASE WHEN EXISTS (
                   SELECT 1 FROM source_snapshot ss
                    WHERE ss.sport=ms.sport
                      AND ss.source=ms.source
                      AND COALESCE(ss.source_url,'')=COALESCE(ms.source_url,'')
                      AND ss.availability_status='EXACT'
                      AND ss.source_available_at_utc IS NOT NULL
                      AND (ss.event_time_utc IS NULL OR ss.event_time_utc=e.event_time_utc)
                 ) THEN 1 ELSE 0 END) AS pit_rows
               FROM match_stats ms
               JOIN event e ON e.event_id=ms.event_id
              WHERE ms.sport=? AND ms.value_num IS NOT NULL
              GROUP BY ms.source, ms.source_url, ms.stat_name
              ORDER BY rows_count DESC, ms.source, ms.stat_name""",
            (sport,),
        ).fetchall()

        source_rows = con.execute(
            """SELECT source, source_url, availability_status,
                      COUNT(*) AS rows_count,
                      SUM(CASE WHEN source_available_at_utc IS NOT NULL THEN 1 ELSE 0 END) AS available_rows
                 FROM source_snapshot
                WHERE sport=?
                GROUP BY source, source_url, availability_status
                ORDER BY rows_count DESC, source""",
            (sport,),
        ).fetchall()

        allowed = set(policy.get(sport) or [])
        feature_usage = []
        for row in rows:
            pit_rows = int(row["pit_rows"] or 0)
            stat_name = str(row["stat_name"])
            feature_usage.append(
                {
                    "source": row["source"],
                    "source_url": row["source_url"],
                    "stat_name": stat_name,
                    "policy_allows_stat": stat_name in allowed,
                    "rows": int(row["rows_count"] or 0),
                    "events": int(row["event_count"] or 0),
                    "pit_usable_rows": pit_rows,
                    "strict_pit_active": bool(stat_name in allowed and pit_rows > 0),
                }
            )

        pit_active = [x for x in feature_usage if x["strict_pit_active"]]
        sources = [
            {
                "source": r["source"],
                "source_url": r["source_url"],
                "availability_status": r["availability_status"],
                "rows": int(r["rows_count"] or 0),
                "available_rows": int(r["available_rows"] or 0),
            }
            for r in source_rows
        ]

        return {
            "db_present": True,
            "events": int(events),
            "verified_outcomes": int(outcomes),
            "exact_snapshots": int(exact),
            "match_stat_rows": int(stat_rows),
            "pit_usable_stat_rows": int(sum(int(x["pit_usable_rows"]) for x in feature_usage if x["stat_name"] in allowed)),
            "sources": sources,
            "feature_usage": feature_usage,
            "active_pit_features": pit_active,
        }
    finally:
        con.close()


def audit(
    sport: str,
    db_path: Path = DB,
    registry_path: Path = REGISTRY,
    policy_path: Path = POLICY_FILE,
    shadow_path: Path = SHADOW,
) -> dict:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    policy = _load_policy(policy_path)
    shadow = _load_shadow(shadow_path)
    evidence = registry.get("evidence") or {}
    shadow_rows = shadow.get("sources") if isinstance(shadow, dict) else []
    shadow_by_source = {str(x.get("source")): x for x in shadow_rows if isinstance(x, dict)}

    db = _query_db(db_path, sport, policy)

    db_registry_sources = {}
    for item in db.get("sources") or []:
        for source_id in _source_registry_match(item.get("source"), item.get("source_url"), _registry_references(registry)):
            db_registry_sources.setdefault(source_id, []).append(item)

    registry_status = {}
    for source_id, item in evidence.items():
        registry_status[source_id] = {
            "registry_status": item.get("status"),
            "db_source_seen": source_id in db_registry_sources,
            "db_rows": sum(int(x.get("rows") or 0) for x in db_registry_sources.get(source_id, [])),
        }

    active_stats = db.get("active_pit_features") or []
    source_feature_active = sorted(
        {
            str(row.get("source"))
            for row in active_stats
            if row.get("source")
        }
    )

    return {
        "audit_version": "source-usage-audit-v1",
        "generated_at_utc": utcnow(),
        "sport": sport,
        "research_only": True,
        "production_model_touched": False,
        "collector_modules_present": COLLECTORS.get(sport, []),
        "policy_stats": sorted(policy.get(sport) or []),
        "database": db,
        "source_feature_active": source_feature_active,
        "registry": registry_status,
        "shadow": {
            "manifest_present": bool(shadow),
            "captured_source_count": len(shadow_by_source),
            "captured_sources": sorted(
                {
                    k: (shadow_by_source[k].get("status"), shadow_by_source[k].get("historical_pit_status"))
                    for k in shadow_by_source
                    if str(shadow_by_source[k].get("sport")) == sport
                }.items()
            ),
        },
        "interpretation": {
            "collector_present_is_not_usage": True,
            "db_source_seen_is_not_pit_safe": True,
            "strict_pit_active_requires_policy_stat_and_exact_snapshot": True,
            "shadow_current_capture_is_not_historical_pit_evidence": True,
            "unknown_availability_is_not_counted_as_pit_safe": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", choices=SPORTS, required=True)
    parser.add_argument("--db", default=str(DB))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    result = audit(args.sport, db_path=Path(args.db))
    output = Path(args.output) if args.output else RESULTS / f"{args.sport}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_json(result), encoding="utf-8")
    print(
        f"SOURCE_USAGE_AUDIT sport={args.sport} "
        f"events={result['database']['events']} "
        f"exact_snapshots={result['database']['exact_snapshots']} "
        f"pit_active_features={len(result['database'].get('active_pit_features') or [])} "
        f"shadow_manifest={result['shadow']['manifest_present']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
