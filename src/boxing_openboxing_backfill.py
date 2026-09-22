from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "db" / "boxing_v45.sqlite"
OUT = ROOT / "results" / "v45" / "boxing_coverage.json"
API_ROOT = "https://openboxing.org/api"
PARSER_VERSION = "boxing-openboxing-v1"
ENDPOINTS = {
    "all": f"{API_ROOT}/bouts/all.json",
    "scheduled": f"{API_ROOT}/bouts/scheduled.json",
}

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

def init_db(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS source_snapshot(
          snapshot_id TEXT PRIMARY KEY,
          source TEXT NOT NULL,
          source_url TEXT NOT NULL,
          retrieved_at_utc TEXT NOT NULL,
          source_available_at_utc TEXT,
          content_hash TEXT NOT NULL,
          parser_version TEXT NOT NULL,
          availability_status TEXT NOT NULL,
          bytes INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bout(
          bout_id TEXT PRIMARY KEY,
          external_bout_id TEXT,
          bout_date TEXT,
          status TEXT,
          weight_class TEXT,
          weight_lb TEXT,
          scheduled_rounds INTEGER,
          winner TEXT,
          method_of_victory TEXT,
          total_rounds INTEGER,
          location_json TEXT,
          titles_json TEXT,
          source_snapshot_id TEXT NOT NULL,
          retrieved_at_utc TEXT NOT NULL,
          FOREIGN KEY(source_snapshot_id) REFERENCES source_snapshot(snapshot_id)
        );
        CREATE TABLE IF NOT EXISTS boxer(
          boxer_id TEXT PRIMARY KEY,
          external_champion_id TEXT,
          first_name TEXT,
          last_name TEXT,
          short_name TEXT,
          born TEXT,
          source_snapshot_id TEXT NOT NULL,
          retrieved_at_utc TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bout_boxer(
          bout_id TEXT NOT NULL,
          boxer_id TEXT NOT NULL,
          side TEXT NOT NULL,
          PRIMARY KEY(bout_id, boxer_id, side),
          FOREIGN KEY(bout_id) REFERENCES bout(bout_id),
          FOREIGN KEY(boxer_id) REFERENCES boxer(boxer_id)
        );
        CREATE INDEX IF NOT EXISTS idx_boxing_bout_date ON bout(bout_date);
        CREATE INDEX IF NOT EXISTS idx_boxing_boxer ON bout_boxer(boxer_id);
        """
    )
    con.commit()

def fetch_json(url: str) -> tuple[dict | list, str]:
    req = Request(url, headers={"User-Agent": "SevenSportBoxingResearch/1.0", "Accept": "application/json"})
    with urlopen(req, timeout=20) as resp:
        raw = resp.read()
    text = raw.decode("utf-8")
    return json.loads(text), hashlib.sha256(raw).hexdigest()

def norm_bouts(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("bouts", "data", "results"):
            if isinstance(data.get(key), list):
                return data[key]
    return []

def sid(source_url: str, content_hash: str) -> str:
    return hashlib.sha256(f"{source_url}|{content_hash}".encode()).hexdigest()[:32]

def main() -> int:
    DB.parent.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    init_db(con)
    reports = []
    total_bouts = 0

    for kind, url in ENDPOINTS.items():
        try:
            payload, content_hash = fetch_json(url)
            retrieved = utcnow()
            snapshot_id = sid(url, content_hash)
            raw_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            con.execute(
                """INSERT OR REPLACE INTO source_snapshot
                   (snapshot_id,source,source_url,retrieved_at_utc,source_available_at_utc,
                    content_hash,parser_version,availability_status,bytes)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (snapshot_id, "openboxing", url, retrieved, None, content_hash,
                 PARSER_VERSION, "UNVERIFIABLE", raw_bytes),
            )
            count = 0
            for b in norm_bouts(payload):
                if not isinstance(b, dict):
                    continue
                ext = str(b.get("boutId") or b.get("bout_id") or "").strip()
                if not ext:
                    continue
                bid = hashlib.sha256(f"boxing|openboxing|{ext}".encode()).hexdigest()[:32]
                weight = b.get("weight") or {}
                result = b.get("result") or {}
                location = b.get("location") or {}
                titles = b.get("titles") or []
                con.execute(
                    """INSERT OR REPLACE INTO bout
                       (bout_id,external_bout_id,bout_date,status,weight_class,weight_lb,
                        scheduled_rounds,winner,method_of_victory,total_rounds,location_json,
                        titles_json,source_snapshot_id,retrieved_at_utc)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (bid, ext, b.get("date"), b.get("status"), weight.get("class"),
                     weight.get("lb"), b.get("scheduledRounds"), result.get("winner"),
                     result.get("methodOfVictory"), result.get("totalRounds"),
                     json.dumps(location, ensure_ascii=False),
                     json.dumps(titles, ensure_ascii=False), snapshot_id, retrieved),
                )
                boxers = b.get("boxers") or {}
                for side, box in (("A", boxers.get("boxerA")), ("B", boxers.get("boxerB"))):
                    if not isinstance(box, dict):
                        continue
                    name = box.get("name") or {}
                    first = str(name.get("first") or "").strip()
                    last = str(name.get("last") or "").strip()
                    short = str(name.get("short") or "").strip()
                    boxer_key = str(box.get("championId") or f"{first}|{last}|{short}").strip()
                    boxer_id = hashlib.sha256(f"boxing|{boxer_key}".encode()).hexdigest()[:32]
                    con.execute(
                        """INSERT OR REPLACE INTO boxer
                           (boxer_id,external_champion_id,first_name,last_name,short_name,born,
                            source_snapshot_id,retrieved_at_utc)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (boxer_id, str(box.get("championId") or "") or None,
                         first, last, short, box.get("born"), snapshot_id, retrieved),
                    )
                    con.execute(
                        "INSERT OR REPLACE INTO bout_boxer(bout_id,boxer_id,side) VALUES(?,?,?)",
                        (bid, boxer_id, side),
                    )
                count += 1
            con.commit()
            total_bouts += count
            reports.append({
                "endpoint": kind,
                "status": "COLLECTED",
                "bouts": count,
                "retrieved_at_utc": retrieved,
                "availability_status": "UNVERIFIABLE",
                "pit_note": "retrieval time is not historical publication availability",
            })
        except Exception as exc:
            reports.append({"endpoint": kind, "status": "DEGRADED", "error": type(exc).__name__})

    report = {
        "sport": "boxing",
        "status": "DEFERRED_PIT",
        "parser_version": PARSER_VERSION,
        "database": str(DB.relative_to(ROOT)),
        "total_bouts_seen_this_run": total_bouts,
        "endpoints": reports,
        "prediction_cutoff_rule": "event_time_minus_60m",
        "production_model_enabled": False,
        "reason": "Open Boxing provides free/open historical and scheduled bout data, but this collector does not claim historical source availability. Boxing remains outside model training until PIT evidence is proven.",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    con.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
