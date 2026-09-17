from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/db/x_social_v1.sqlite"
RAW = ROOT / "data/raw/x"
API_RECENT = "https://api.x.com/2/tweets/search/recent"
API_ALL = "https://api.x.com/2/tweets/search/all"
PARSER_VERSION = "x-social-v1-exact-provenance"

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS source_snapshot (
  snapshot_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  source_url TEXT NOT NULL,
  retrieved_at_utc TEXT NOT NULL,
  source_available_at_utc TEXT,
  content_hash TEXT NOT NULL,
  payload_path TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  availability_status TEXT NOT NULL,
  provenance_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS x_post (
  post_id TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL,
  event_id TEXT,
  sport TEXT,
  side TEXT,
  author_id TEXT,
  username TEXT,
  created_at_utc TEXT NOT NULL,
  text TEXT NOT NULL,
  like_count INTEGER,
  reply_count INTEGER,
  repost_count INTEGER,
  quote_count INTEGER,
  observed_at_utc TEXT NOT NULL,
  source_available_at_utc TEXT,
  pit_status TEXT NOT NULL,
  FOREIGN KEY(snapshot_id) REFERENCES source_snapshot(snapshot_id)
);
CREATE INDEX IF NOT EXISTS idx_x_post_event_time ON x_post(event_id, created_at_utc);
CREATE INDEX IF NOT EXISTS idx_x_post_pit ON x_post(event_id, source_available_at_utc);
"""


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    value = str(value).replace("Z", "+00:00")
    result = datetime.fromisoformat(value)
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def stable_id(*values: object) -> str:
    raw = "|".join("" if value is None else str(value) for value in values)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB)
    connection.executescript(SCHEMA)
    return connection


def parse_payload(payload: object):
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        users = {
            str(user.get("id")): user
            for user in payload.get("includes", {}).get("users", [])
            if user.get("id")
        }
        return [(post, users.get(str(post.get("author_id")))) for post in payload["data"]]
    if isinstance(payload, list):
        return [(post, None) for post in payload]
    return [(payload, None)]


def ingest_payload(
    payload: object,
    *,
    source_url: str,
    retrieved_at_utc: str,
    source_available_at_utc: str | None = None,
    event_id: str | None = None,
    sport: str | None = None,
    side: str | None = None,
) -> dict:
    """Store raw X data without making it production-model input.

    Historical PIT eligibility requires an explicit source_available_at_utc. A
    retrieval timestamp alone is deliberately insufficient for reconstructing
    historical availability.
    """
    connection = connect()
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    content_hash = hashlib.sha256(raw).hexdigest()
    snapshot_id = stable_id("x-source", source_url, content_hash, retrieved_at_utc)
    RAW.mkdir(parents=True, exist_ok=True)
    payload_path = RAW / f"{snapshot_id}.json"
    payload_path.write_bytes(raw)

    availability_status = "EXACT" if source_available_at_utc else "UNVERIFIABLE"
    provenance = {
        "source": "X API",
        "endpoint": source_url,
        "retrieved_at_utc": retrieved_at_utc,
        "source_available_at_utc": source_available_at_utc,
        "historical_pit_rule": "source_available_at_utc is mandatory for historical PIT eligibility",
    }
    connection.execute(
        """INSERT OR REPLACE INTO source_snapshot
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            snapshot_id,
            "X",
            source_url,
            retrieved_at_utc,
            source_available_at_utc,
            content_hash,
            str(payload_path.relative_to(ROOT)),
            PARSER_VERSION,
            availability_status,
            json.dumps(provenance, ensure_ascii=False),
        ),
    )

    inserted = 0
    deferred = 0
    for post, user in parse_payload(payload):
        if not post.get("id") or not post.get("created_at") or not isinstance(post.get("text"), str):
            continue
        metrics = post.get("public_metrics") or {}
        post_created = post["created_at"]
        pit_status = (
            "ELIGIBLE"
            if source_available_at_utc and parse_dt(source_available_at_utc) <= parse_dt(post_created)
            else "DEFERRED"
        )
        if pit_status == "DEFERRED":
            deferred += 1
        connection.execute(
            """INSERT OR REPLACE INTO x_post
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(post["id"]),
                snapshot_id,
                event_id,
                sport,
                side,
                str(post.get("author_id") or ""),
                str((user or {}).get("username") or ""),
                post_created,
                post["text"],
                int(metrics.get("like_count", 0) or 0),
                int(metrics.get("reply_count", 0) or 0),
                int(metrics.get("retweet_count", metrics.get("repost_count", 0)) or 0),
                int(metrics.get("quote_count", 0) or 0),
                retrieved_at_utc,
                source_available_at_utc,
                pit_status,
            ),
        )
        inserted += 1
    connection.commit()
    connection.close()
    return {
        "status": "OK",
        "snapshot_id": snapshot_id,
        "posts": inserted,
        "deferred_posts": deferred,
        "availability_status": availability_status,
        "payload_path": str(payload_path.relative_to(ROOT)),
    }


def collect(args: argparse.Namespace) -> int:
    token = os.environ.get("X_BEARER_TOKEN") or os.environ.get("BEARER_TOKEN")
    if not token:
        print(json.dumps({
            "status": "DEFERRED_NO_CREDENTIALS",
            "reason": "X_BEARER_TOKEN/BEARER_TOKEN is not configured; no unauthenticated collection is attempted",
            "production_model_touched": False,
        }, ensure_ascii=False, indent=2))
        return 0

    endpoint = API_ALL if args.archive else API_RECENT
    params = {
        "query": args.query,
        "max_results": str(min(args.max_results, 500 if args.archive else 100)),
        "tweet.fields": "created_at,public_metrics,author_id",
        "expansions": "author_id",
        "user.fields": "username,verified",
    }
    if args.start_time:
        params["start_time"] = args.start_time
    if args.end_time:
        params["end_time"] = args.end_time

    total = 0
    pages = 0
    next_token = None
    while pages < args.max_pages:
        if next_token:
            params["next_token"] = next_token
        url = endpoint + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        retrieved_at = now_utc()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except Exception as exc:
            print(json.dumps({
                "status": "DEFERRED_FETCH_ERROR",
                "error": str(exc),
                "pages": pages,
                "posts": total,
                "production_model_touched": False,
            }, ensure_ascii=False, indent=2))
            return 0

        # For live collection, the server retrieval time is the earliest defensible
        # availability timestamp. Historical PIT backfills must provide their own
        # explicit capture timestamp through `ingest`.
        result = ingest_payload(
            payload,
            source_url=endpoint,
            retrieved_at_utc=retrieved_at,
            source_available_at_utc=retrieved_at,
            event_id=args.event_id,
            sport=args.sport,
            side=args.side,
        )
        total += result["posts"]
        pages += 1
        next_token = (payload.get("meta") or {}).get("next_token")
        if not next_token:
            break

    print(json.dumps({
        "status": "OK",
        "endpoint": endpoint,
        "pages": pages,
        "posts": total,
        "pit_rule": "only source_available_at_utc <= prediction cutoff may be used",
        "production_model_touched": False,
    }, ensure_ascii=False, indent=2))
    return 0


def ingest_file(args: argparse.Namespace) -> int:
    path = Path(args.input)
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(json.dumps(ingest_payload(
        payload,
        source_url=args.source_url,
        retrieved_at_utc=args.retrieved_at,
        source_available_at_utc=args.source_available_at,
        event_id=args.event_id,
        sport=args.sport,
        side=args.side,
    ), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated X-data collection/PIT storage layer")
    sub = parser.add_subparsers(dest="command", required=True)

    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--query", required=True)
    collect_parser.add_argument("--archive", action="store_true")
    collect_parser.add_argument("--start-time")
    collect_parser.add_argument("--end-time")
    collect_parser.add_argument("--max-results", type=int, default=100)
    collect_parser.add_argument("--max-pages", type=int, default=5)
    collect_parser.add_argument("--event-id")
    collect_parser.add_argument("--sport")
    collect_parser.add_argument("--side", choices=["A", "B"])
    collect_parser.set_defaults(handler=collect)

    ingest_parser = sub.add_parser("ingest")
    ingest_parser.add_argument("--input", required=True)
    ingest_parser.add_argument("--source-url", required=True)
    ingest_parser.add_argument("--retrieved-at", default=now_utc())
    ingest_parser.add_argument("--source-available-at")
    ingest_parser.add_argument("--event-id")
    ingest_parser.add_argument("--sport")
    ingest_parser.add_argument("--side", choices=["A", "B"])
    ingest_parser.set_defaults(handler=ingest_file)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
