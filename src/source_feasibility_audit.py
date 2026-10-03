from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "SOURCE_FEASIBILITY_POLICY.json"
DEFAULT_OUT = ROOT / "results" / "source_feasibility.json"
UA = os.getenv("SPORTS_PIPELINE_USER_AGENT", "SevenSportResearchEngine/source-feasibility-v1")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_policy() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def _safe_text(response: requests.Response) -> str:
    try:
        return response.text or ""
    except Exception:
        return ""


def probe_source(source: dict, timeout: float = 20.0) -> dict:
    url = str(source["url"])
    result = {
        "source_id": str(source["source_id"]),
        "name": str(source["name"]),
        "url": url,
        "kind": str(source.get("kind") or ""),
        "critical": bool(source.get("critical", False)),
        "capabilities": list(source.get("capabilities") or []),
        "configured_pit_status": str(source.get("pit_status") or "UNPROVEN"),
        "checked_at_utc": _utcnow(),
        "http_status": None,
        "reachable": False,
        "nonempty": False,
        "content_length": 0,
        "signals_required": list(source.get("required_signals") or []),
        "signals_found": [],
        "signals_missing": [],
        "status": "ERROR",
        "historical_availability_status": "UNKNOWN",
        "pit_status": "UNPROVEN",
        "pit_proof_source": "reachability_probe_cannot_prove_historical_PIT",
        "content_sha256": None,
        "error": None,
    }
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": UA,
                "Accept-Language": "en-US,en;q=0.8,ja;q=0.6",
            },
            timeout=(10.0, timeout),
        )
        text = _safe_text(response)
        result["http_status"] = int(response.status_code)
        result["content_length"] = len(response.content or b"")
        result["reachable"] = 200 <= response.status_code < 400
        result["nonempty"] = bool(text.strip() or response.content)
        result["content_sha256"] = hashlib.sha256(response.content or b"").hexdigest()
        result["signals_found"] = [
            signal for signal in result["signals_required"]
            if signal.lower() in text.lower()
        ]
        result["signals_missing"] = [
            signal for signal in result["signals_required"]
            if signal.lower() not in text.lower()
        ]
        if result["reachable"] and result["nonempty"] and not result["signals_missing"]:
            result["status"] = "REACHABLE_WITH_EXPECTED_SIGNALS"
        elif result["reachable"] and result["nonempty"]:
            result["status"] = "REACHABLE_SIGNALS_PARTIAL"
        elif result["reachable"]:
            result["status"] = "REACHABLE_EMPTY"
        else:
            result["status"] = "HTTP_UNREACHABLE"
    except requests.RequestException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["status"] = "REQUEST_ERROR"
    return result


def build_report(policy: dict, timeout: float = 20.0) -> dict:
    sports = {}
    failures = []
    for sport, sources in (policy.get("active_sports") or {}).items():
        rows = [probe_source(source, timeout=timeout) for source in sources]
        critical = [row for row in rows if row["critical"]]
        critical_ok = any(
            row["status"] == "REACHABLE_WITH_EXPECTED_SIGNALS"
            for row in critical
        )
        if critical_ok:
            sport_status = "SOURCE_REACHABLE"
        else:
            sport_status = "DATA_SOURCE_OUTAGE"
            failures.append({
                "sport": sport,
                "failure_class": "critical_source_unavailable",
                "sources": rows,
            })
        sports[sport] = {
            "status": sport_status,
            "current_source_count": sum(row["reachable"] for row in rows),
            "critical_source_reachable": critical_ok,
            "sources": rows,
        }
    return {
        "version": "source-feasibility-v1",
        "checked_at_utc": _utcnow(),
        "status": "PASS" if not failures else "DEGRADED",
        "sport_status": sports,
        "failures": failures,
        "interpretation": {
            "SOURCE_REACHABLE": "Current endpoint is reachable and contains expected signals.",
            "DEGRADED": "One or more critical source checks failed; prediction coverage requires explicit fallback or gap handling.",
            "historical_availability_status": "Reachability alone does not establish historical availability.",
            "pit_status": "UNPROVEN unless independently backed by source-availability evidence.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe public/free active-sport sources and separate reachability from historical PIT proof."
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    policy = _load_policy()
    report = build_report(policy, timeout=max(5.0, float(args.timeout)))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    # A transient source outage is intentionally represented as DEGRADED and
    # returns non-zero so callers cannot mistake it for a successful coverage run.
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
