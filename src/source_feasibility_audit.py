from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import os
import re
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


def _normalise_html_text(text: str) -> str:
    # Search rendered text rather than raw HTML. Public pages frequently split
    # labels across tags, so raw-substring matching can produce false negatives.
    stripped = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html_lib.unescape(stripped)).strip()


def _first_json_collection(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "events", "results", "items", "matches", "fights"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _json_key_group_present(rows, group) -> bool:
    wanted = {str(x).lower() for x in group}
    for row in rows:
        if isinstance(row, dict):
            actual = {str(k).lower() for k in row}
            if actual.intersection(wanted):
                return True
    return False


def _probe_expected_shape(response: requests.Response, source: dict) -> dict:
    mode = str(source.get("probe_mode") or "html_text").lower()
    if mode not in {"json_collection", "json"}:
        return {
            "mode": "html_text",
            "valid": True,
            "record_count": None,
            "missing_key_groups": [],
        }
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return {
            "mode": mode,
            "valid": False,
            "record_count": 0,
            "missing_key_groups": ["valid_json"],
        }
    rows = _first_json_collection(payload)
    missing = []
    minimum = max(0, int(source.get("minimum_records", 1)))
    if len(rows) < minimum:
        missing.append(f"minimum_records>={minimum}")
    for idx, group in enumerate(source.get("required_json_key_groups") or [], start=1):
        keys = list(group) if isinstance(group, (list, tuple)) else [group]
        if not _json_key_group_present(rows[:20], keys):
            missing.append(f"key_group_{idx}:{'|'.join(str(k) for k in keys)}")
    return {
        "mode": mode,
        "valid": not missing,
        "record_count": len(rows),
        "missing_key_groups": missing,
    }


def probe_source(source: dict, timeout: float = 20.0, retries: int = 3) -> dict:
    url = str(source["url"])
    result = {
        "source_id": str(source["source_id"]),
        "name": str(source["name"]),
        "url": url,
        "probe_url": str(source.get("probe_url") or url),
        "kind": str(source.get("kind") or ""),
        "critical": bool(source.get("critical", False)),
        "capabilities": list(source.get("capabilities") or []),
        "configured_pit_status": str(source.get("pit_status") or "UNPROVEN"),
        "checked_at_utc": _utcnow(),
        "attempts": 0,
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
        "content_probe_mode": str(source.get("probe_mode") or "html_text"),
        "data_shape": {
            "mode": str(source.get("probe_mode") or "html_text"),
            "valid": False,
            "record_count": None,
            "missing_key_groups": [],
        },
        "error": None,
    }
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.8,ja;q=0.6",
    })
    last_error = None
    for attempt in range(1, max(1, int(retries)) + 1):
        result["attempts"] = attempt
        try:
            probe_url = str(source.get("probe_url") or url)
            response = session.get(
                probe_url,
                timeout=(10.0, timeout),
            )
            text = _safe_text(response)
            mode = str(source.get("probe_mode") or "html_text").lower()
            if mode in {"json_collection", "json"}:
                try:
                    payload = response.json()
                    search_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                except (ValueError, TypeError):
                    search_text = text
            else:
                search_text = _normalise_html_text(text)
            result["http_status"] = int(response.status_code)
            result["content_length"] = len(response.content or b"")
            result["reachable"] = 200 <= response.status_code < 400
            result["nonempty"] = bool(text.strip() or response.content)
            result["content_sha256"] = hashlib.sha256(response.content or b"").hexdigest()
            result["content_probe_mode"] = mode
            result["data_shape"] = _probe_expected_shape(response, source)
            result["signals_found"] = [
                signal for signal in result["signals_required"]
                if signal.lower() in search_text.lower()
            ]
            result["signals_missing"] = [
                signal for signal in result["signals_required"]
                if signal.lower() not in search_text.lower()
            ]
            shape_ok = bool(result["data_shape"]["valid"])
            if result["reachable"] and result["nonempty"] and not result["signals_missing"] and shape_ok:
                result["status"] = "REACHABLE_WITH_EXPECTED_SIGNALS"
                result["error"] = None
                return result
            if result["reachable"] and result["nonempty"]:
                result["status"] = "REACHABLE_SIGNALS_PARTIAL"
                result["error"] = None
                return result
            if result["reachable"]:
                result["status"] = "REACHABLE_EMPTY"
                result["error"] = None
                return result
            if response.status_code not in {429} and not (500 <= response.status_code < 600):
                result["status"] = "HTTP_UNREACHABLE"
                result["error"] = f"http_status={response.status_code}"
                return result
            last_error = f"http_status={response.status_code}"
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < max(1, int(retries)):
            import time
            time.sleep(min(4.0, 0.75 * (2 ** (attempt - 1))))

    result["error"] = last_error
    result["status"] = "REQUEST_ERROR" if last_error else "HTTP_UNREACHABLE"
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
