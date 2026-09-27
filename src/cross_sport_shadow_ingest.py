from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "cross_sport_shadow"
RAW = ROOT / "data" / "raw" / "cross_sport_shadow"


@dataclass(frozen=True)
class SourceSpec:
    source: str
    sport: str
    url: str
    kind: str


SOURCES = (
    SourceSpec("f1api_dev", "f1", "https://f1api.dev/api/current", "json"),
    SourceSpec("wta_official", "tennis", "https://api.wtatennis.com/tennis/players/ranked?type=rankSingles&metric=singles&pageSize=25", "json"),
    SourceSpec("euroleague_official", "basketball", "https://api-live.euroleague.net/v2/seasons/E", "json"),
    SourceSpec("openboxing", "boxing", "https://raw.githubusercontent.com/edhwright/open-boxing/main/src/db/data/bouts.csv", "csv"),
    SourceSpec("rizin_club", "rizin", "https://rizin.club/", "html"),
    SourceSpec("world_rugby_official_archive", "rugby", "https://www.world.rugby/", "html"),
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch(spec: SourceSpec, timeout: float = 15.0) -> tuple[bytes, int, str, str]:
    req = urllib.request.Request(
        spec.url,
        headers={
            "User-Agent": "NineSportResearchEngine/ShadowSource/1.0",
            "Accept": "application/json,text/csv,text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8,ja;q=0.6",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(), int(response.status), response.geturl(), str(response.headers.get("Content-Type") or "")


def summarize(spec: SourceSpec, body: bytes, status_code: int, final_url: str, content_type: str, retrieved_at: str) -> dict:
    digest = hashlib.sha256(body).hexdigest()
    root = RAW / spec.source
    root.mkdir(parents=True, exist_ok=True)
    suffix = {"json": ".json", "csv": ".csv", "html": ".html"}[spec.kind]
    payload_path = root / f"{digest}{suffix}"
    payload_path.write_bytes(body)

    result = {
        "source": spec.source,
        "sport": spec.sport,
        "requested_url": spec.url,
        "final_url": final_url,
        "kind": spec.kind,
        "status_code": status_code,
        "retrieved_at_utc": retrieved_at,
        "content_type": content_type,
        "content_sha256": digest,
        "bytes": len(body),
        "payload_path": str(payload_path.relative_to(ROOT)),
        "historical_pit_status": "UNPROVEN",
        "research_only": True,
        "production_model_touched": False,
    }

    if spec.kind == "json":
        try:
            payload = json.loads(body.decode("utf-8"))
            result["parseable"] = True
            result["payload_shape"] = type(payload).__name__
            if isinstance(payload, dict):
                result["top_keys"] = sorted(str(k) for k in payload.keys())[:50]
                result["record_count"] = max(
                    [
                        len(v)
                        for v in payload.values()
                        if isinstance(v, list)
                    ]
                    or [0]
                )
            elif isinstance(payload, list):
                result["record_count"] = len(payload)
            else:
                result["record_count"] = 0
        except (UnicodeDecodeError, json.JSONDecodeError):
            result["parseable"] = False
            result["error"] = "json_parse_failed"
    elif spec.kind == "csv":
        text = body.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
        nonempty = [row for row in rows if any(str(cell).strip() for cell in row)]
        result["parseable"] = bool(nonempty)
        result["record_count"] = max(0, len(nonempty) - 1)
        result["header"] = [str(x).strip() for x in nonempty[0]][:100] if nonempty else []
    else:
        text = body.decode("utf-8", errors="replace")
        result["parseable"] = bool(text.strip())
        title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        result["title"] = re.sub(r"\s+", " ", title.group(1)).strip() if title else None

    return result


def collect_source(spec: SourceSpec) -> dict:
    started = datetime.now(timezone.utc)
    retrieved_at = started.isoformat()
    try:
        body, status_code, final_url, content_type = fetch(spec)
        if not body or not (200 <= status_code < 400):
            return {
                "source": spec.source,
                "sport": spec.sport,
                "requested_url": spec.url,
                "status": "DEGRADED",
                "status_code": status_code,
                "retrieved_at_utc": retrieved_at,
                "error": "empty_or_non_success_response",
                "research_only": True,
                "production_model_touched": False,
            }
        summary = summarize(spec, body, status_code, final_url, content_type, retrieved_at)
        summary["status"] = "PASS"
        return summary
    except urllib.error.HTTPError as exc:
        return {
            "source": spec.source,
            "sport": spec.sport,
            "requested_url": spec.url,
            "status": "DEGRADED",
            "status_code": int(exc.code),
            "retrieved_at_utc": retrieved_at,
            "error": f"HTTPError:{exc.code}",
            "research_only": True,
            "production_model_touched": False,
        }
    except Exception as exc:
        return {
            "source": spec.source,
            "sport": spec.sport,
            "requested_url": spec.url,
            "status": "DEGRADED",
            "retrieved_at_utc": retrieved_at,
            "error": f"{type(exc).__name__}:{exc}",
            "research_only": True,
            "production_model_touched": False,
        }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [collect_source(spec) for spec in SOURCES]
    report = {
        "version": "cross-sport-shadow-ingest-v1",
        "generated_at_utc": utcnow(),
        "research_only": True,
        "production_model_touched": False,
        "historical_pit_status": "UNPROVEN",
        "sources": rows,
        "source_count": len(rows),
        "healthy_count": sum(1 for row in rows if row.get("status") == "PASS"),
        "degraded_count": sum(1 for row in rows if row.get("status") != "PASS"),
        "policy": (
            "free/no-key candidates only; current retrieval is captured as evidence of "
            "current availability, never as historical availability; no production feature/model writes"
        ),
    }
    (OUT / "shadow_sources.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # A degraded candidate is evidence, not a hidden success. The shadow job remains
    # green so one provider outage does not mask or cancel the remaining captures.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
