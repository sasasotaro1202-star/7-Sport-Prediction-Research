from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sqlite3
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.storage.db_v45 import utcnow

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data/db/sports_v45.sqlite"
UPSTREAM_REPO = "https://github.com/Greco1899/scrape_ufc_stats.git"
UPSTREAM_SOURCE = "Greco1899/scrape_ufc_stats"
UPSTREAM_FILE = "ufc_fight_stats.csv"
PARSER_VERSION = "ufc-greco-stat-pit-v1"

STAT_FIELDS = {
    "sig_str": "SIG.STR.",
    "takedown": "TD",
    "sub_attempts": "SUB.ATT",
    "control_time": "CTRL",
}
CANONICAL_HEADER = [
    "EVENT","BOUT","ROUND","FIGHTER","KD","SIG.STR.","SIG.STR. %",
    "TOTAL STR.","TD","TD %","SUB.ATT","REV.","CTRL","HEAD","BODY",
    "LEG","DISTANCE","CLINCH","GROUND",
]

def _norm(value: str | None) -> str:
    return " ".join(str(value or "").strip().casefold().replace(".", " . ").split()).replace(" . ", " ")

def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _run(args: list[str], cwd: Path | None = None) -> str:
    p = subprocess.run(
        args, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    return p.stdout

def _parse_fraction(value: str | None) -> tuple[float, float] | None:
    text = str(value or "").strip()
    if not text or text in {"--", "---", "-"} or "of" not in text:
        return None
    parts = text.split("of", 1)
    try:
        landed, attempted = float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None
    if not all(x == x and abs(x) != float("inf") for x in (landed, attempted)):
        return None
    if landed < 0 or attempted < 0 or landed > attempted:
        return None
    return landed, attempted

def _parse_float(value: str | None) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"--", "---", "-"}:
        return None
    try:
        x = float(text)
    except ValueError:
        return None
    return x if x == x and abs(x) != float("inf") and x >= 0 else None

def _parse_control(value: str | None) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"--", "---", "-"}:
        return None
    if ":" not in text:
        return _parse_float(text)
    try:
        minutes, seconds = (int(x) for x in text.split(":", 1))
    except ValueError:
        return None
    if minutes < 0 or seconds < 0 or seconds >= 60:
        return None
    return float(minutes * 60 + seconds)

def _round_number(value: str | None) -> int | None:
    text = str(value or "").strip().casefold()
    if not text.startswith("round"):
        return None
    try:
        n = int(text.split()[-1])
    except ValueError:
        return None
    return n if n >= 1 else None

def _header_map(header: list[str]) -> dict[str, int]:
    h = {str(name).strip(): i for i, name in enumerate(header)}
    required = {"EVENT", "BOUT", "ROUND", "FIGHTER", "SIG.STR.", "TD", "SUB.ATT", "CTRL"}
    missing = sorted(required - set(h))
    if missing:
        raise RuntimeError(f"upstream_header_missing:{','.join(missing)}")
    return h

def _parse_data_row(row: list[str], header: list[str]) -> dict | None:
    if len(row) != len(header):
        return None
    h = _header_map(header)
    event, bout, fighter = (str(row[h[k]]).strip() for k in ("EVENT", "BOUT", "FIGHTER"))
    round_no = _round_number(row[h["ROUND"]])
    if not event or not bout or not fighter or round_no is None:
        return None
    return {
        "event": event, "event_key": _norm(event), "bout": bout, "bout_key": _norm(bout),
        "fighter": fighter, "fighter_key": _norm(fighter), "round": round_no,
        "sig_str": _parse_fraction(row[h["SIG.STR."]]),
        "takedown": _parse_fraction(row[h["TD"]]),
        "sub_attempts": _parse_float(row[h["SUB.ATT"]]),
        "control_time": _parse_control(row[h["CTRL"]]),
    }

def _added_rows(diff_text: str) -> list[list[str]]:
    out, current_file = [], None
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            current_file = None
            continue
        if raw.startswith("+++ b/"):
            current_file = raw[6:].strip()
            continue
        if current_file != UPSTREAM_FILE or not raw.startswith("+") or raw.startswith("+++"):
            continue
        try:
            out.append(next(csv.reader([raw[1:]])))
        except csv.Error:
            continue
    return out

def _iter_commits(repo_dir: Path) -> list[tuple[str, datetime]]:
    raw = _run(["git", "log", "--reverse", "--format=%H%x09%cI", "--", UPSTREAM_FILE], cwd=repo_dir)
    commits = []
    for line in raw.splitlines():
        if line.strip():
            sha, ts = line.split("\t", 1)
            commits.append((sha, _parse_dt(ts)))
    if not commits:
        raise RuntimeError("upstream_stats_history_empty")
    return commits

def _collect_first_numeric(repo_dir: Path):
    first, commits = {}, _iter_commits(repo_dir)
    rows_added = commits_with_additions = 0
    for sha, commit_time in commits:
        diff = _run(
            ["git", "show", "--root", "--format=", "--unified=0", "--diff-filter=AM", sha, "--", UPSTREAM_FILE],
            cwd=repo_dir,
        )
        added = _added_rows(diff)
        if not added:
            continue
        commits_with_additions += 1
        rows_added += len(added)
        for raw in added:
            if raw and raw[0].strip() == "EVENT":
                continue
            parsed = _parse_data_row(raw, CANONICAL_HEADER)
            if parsed is None:
                continue
            for stat in STAT_FIELDS:
                if parsed[stat] is None:
                    continue
                key = (parsed["event_key"], parsed["bout_key"], parsed["round"], parsed["fighter_key"], stat)
                first.setdefault(key, {"commit": sha, "commit_time": commit_time})
    return first, commits, rows_added, commits_with_additions

def _load_local_maps(con):
    event_map = defaultdict(list)
    for eid, competition, et in con.execute(
        "SELECT event_id, COALESCE(competition_id,''), event_time_utc FROM event WHERE sport='ufc' AND event_time_utc IS NOT NULL"
    ):
        event_map[_norm(competition)].append(str(eid))
    participants = defaultdict(list)
    for pid, name in con.execute("SELECT participant_id, canonical_name FROM participant WHERE sport='ufc'"):
        key = _norm(name)
        if key:
            participants[key].append(str(pid))
    event_participants = defaultdict(set)
    for eid, pid, side in con.execute(
        "SELECT event_id, participant_id, side FROM event_participant WHERE sport='ufc' AND side IN ('A','B') AND participant_id IS NOT NULL"
    ):
        event_participants[str(eid)].add(str(pid))
    event_times = {
        str(eid): _parse_dt(et)
        for eid, et in con.execute("SELECT event_id,event_time_utc FROM event WHERE sport='ufc' AND event_time_utc IS NOT NULL")
    }
    return event_map, participants, event_participants, event_times

def _candidate_groups(first, con):
    event_map, participants, event_participants, event_times = _load_local_maps(con)
    groups = defaultdict(dict)
    for (event_key, bout_key, round_no, fighter_key, stat), obs in first.items():
        groups[(event_key, bout_key, fighter_key, stat)][round_no] = obs

    candidates, skipped = [], 0
    for (event_key, bout_key, fighter_key, stat), rounds in groups.items():
        eids = event_map.get(event_key, [])
        pids = participants.get(fighter_key, [])
        if len(eids) != 1 or len(pids) != 1:
            skipped += 1
            continue
        eid, pid = eids[0], pids[0]
        if pid not in event_participants.get(eid, set()):
            skipped += 1
            continue
        required = set(range(1, max(rounds) + 1))
        if not required.issubset(rounds):
            skipped += 1
            continue
        last = max((rounds[r] for r in required), key=lambda x: (x["commit_time"], x["commit"]))
        candidates.append({
            "event_id": eid, "event_time": event_times[eid], "participant_id": pid,
            "event_key": event_key, "bout_key": bout_key, "fighter_key": fighter_key,
            "stat": stat, "rounds": sorted(required),
            "available_at": last["commit_time"], "available_commit": last["commit"],
        })

    unique = {}
    for c in candidates:
        key = (c["event_id"], c["participant_id"], c["stat"], tuple(c["rounds"]))
        old = unique.get(key)
        if old is None or (c["available_at"], c["available_commit"]) < (old["available_at"], old["available_commit"]):
            unique[key] = c
    return list(unique.values()), len(candidates), skipped

def _read_commit_targets(repo_dir: Path, sha: str, wanted: set[tuple[str, str, str]]):
    raw = _run(["git", "show", f"{sha}:{UPSTREAM_FILE}"], cwd=repo_dir)
    reader = csv.reader(io.StringIO(raw))
    header = next(reader)
    _header_map(header)
    rows = defaultdict(list)
    for row in reader:
        parsed = _parse_data_row(row, header)
        if parsed is None:
            continue
        key = (parsed["event_key"], parsed["bout_key"], parsed["fighter_key"])
        if key in wanted:
            rows[key].append(parsed)
    digest = hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()
    return rows, digest

def _aggregate(rows: list[dict], candidate: dict):
    by_round = {r["round"]: r for r in rows if r["round"] in set(candidate["rounds"])}
    if any(rn not in by_round for rn in candidate["rounds"]):
        return None
    selected = [by_round[rn] for rn in candidate["rounds"]]
    if any(x is None for row in selected for x in (row["sig_str"], row["takedown"], row["sub_attempts"], row["control_time"])):
        return None
    sig = float(sum(x["sig_str"][0] for x in selected))
    td_landed = float(sum(x["takedown"][0] for x in selected))
    td_attempts = float(sum(x["takedown"][1] for x in selected))
    return {
        "sig_str": sig,
        "takedown": td_landed,
        "td_pct": 0.0 if td_attempts == 0 else 100.0 * td_landed / td_attempts,
        "sub_attempts": float(sum(x["sub_attempts"] for x in selected)),
        "control_time": float(sum(x["control_time"] for x in selected)),
    }

def _snapshot_id(commit: str, digest: str) -> str:
    return hashlib.sha256(f"{UPSTREAM_SOURCE}|{commit}|{digest}".encode()).hexdigest()[:32]

def run_backfill(db_path: Path, repo_dir: Path) -> dict:
    first, commits, rows_added, commits_with_additions = _collect_first_numeric(repo_dir)
    with sqlite3.connect(db_path) as con:
        candidates, matched, skipped = _candidate_groups(first, con)
        by_commit = defaultdict(list)
        for c in candidates:
            by_commit[c["available_commit"]].append(c)

        verified, failed = [], 0
        commit_cache = {}
        for commit, cs in sorted(by_commit.items()):
            wanted = {(c["event_key"], c["bout_key"], c["fighter_key"]) for c in cs}
            commit_cache[commit] = _read_commit_targets(repo_dir, commit, wanted)
            target_rows, digest = commit_cache[commit]
            for c in cs:
                aggregate = _aggregate(target_rows.get((c["event_key"], c["bout_key"], c["fighter_key"]), []), c)
                if aggregate is None:
                    failed += 1
                    continue
                x = dict(c)
                x["aggregate"], x["content_hash"] = aggregate, digest
                verified.append(x)

        commit_times = dict(commits)
        snapshot_seen = {}
        inserted = 0
        touched = set()
        for c in verified:
            commit = c["available_commit"]
            skey = (commit, c["content_hash"])
            sid = snapshot_seen.get(skey)
            if sid is None:
                source_url = f"https://raw.githubusercontent.com/{UPSTREAM_SOURCE}/{commit}/{UPSTREAM_FILE}"
                sid = _snapshot_id(commit, c["content_hash"])
                con.execute(
                    """INSERT OR REPLACE INTO source_snapshot(
                       snapshot_id,sport,source,source_url,retrieved_at_utc,
                       source_available_at_utc,event_time_utc,content_hash,
                       parser_version,availability_status,provenance_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        sid, "ufc", UPSTREAM_SOURCE, source_url, utcnow(),
                        commit_times[commit].isoformat(), None, c["content_hash"],
                        PARSER_VERSION, "EXACT",
                        json.dumps({
                            "repository": UPSTREAM_SOURCE, "commit": commit,
                            "commit_time_utc": commit_times[commit].isoformat(),
                            "file": UPSTREAM_FILE,
                            "availability_basis": "public_git_commit_timestamp",
                            "scope": "full immutable file snapshot at fixed commit",
                            "non_claim": "commit time is not claimed as original UFCStats web publication time",
                        }, ensure_ascii=False),
                    ),
                )
                snapshot_seen[skey] = sid
            source_url = f"https://raw.githubusercontent.com/{UPSTREAM_SOURCE}/{commit}/{UPSTREAM_FILE}"
            for stat_name, value in c["aggregate"].items():
                stat_id = hashlib.sha256(
                    f"greco-pit|{c['event_id']}|{c['participant_id']}|{stat_name}|{commit}|{value}".encode()
                ).hexdigest()[:32]
                con.execute(
                    """INSERT OR REPLACE INTO match_stats(
                       stat_id,event_id,participant_id,team_id,sport,observed_at_utc,
                       effective_at_utc,stat_name,value_num,value_text,unit,
                       source,source_url,quality_status,confidence)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        stat_id, c["event_id"], c["participant_id"], None, "ufc",
                        utcnow(), c["event_time"].isoformat(), stat_name, float(value),
                        str(value), "seconds" if stat_name == "control_time" else None,
                        UPSTREAM_SOURCE, source_url, "EXACT", 1.0,
                    ),
                )
                inserted += 1
                touched.add(c["event_id"])
        con.commit()

    return {
        "status": "RESEARCH_DB_ONLY",
        "parser_version": PARSER_VERSION,
        "upstream_repo": UPSTREAM_SOURCE,
        "upstream_file": UPSTREAM_FILE,
        "commits_scanned": len(commits),
        "commits_with_additions": commits_with_additions,
        "rows_added_scanned": rows_added,
        "first_numeric_observations": len(first),
        "candidate_groups_matched": matched,
        "candidate_groups_skipped": skipped,
        "candidate_groups_verified_at_commit": len(verified),
        "candidate_groups_failed_snapshot_content": failed,
        "source_snapshots_created": len(snapshot_seen),
        "inserted_stat_rows": inserted,
        "touched_local_events": len(touched),
        "production_model_changed": False,
        "provenance_status": "EXACT_FIXED_GIT_SNAPSHOT",
        "pit_rule": "source_available_at_utc <= prediction_cutoff",
        "caution": "Git commit timestamp is a conservative public-availability bound, not the original web-publication timestamp.",
    }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--upstream-dir", required=True)
    ap.add_argument("--output", default=str(ROOT / "results/ufc_greco_stat_pit.json"))
    args = ap.parse_args()
    db = Path(args.db)
    repo_dir = Path(args.upstream_dir)
    if not db.is_file():
        raise SystemExit(f"FAIL_CLOSED_DB_MISSING:{db}")
    if not (repo_dir / ".git").is_dir():
        raise SystemExit(f"FAIL_CLOSED_UPSTREAM_REPO_MISSING:{repo_dir}")
    report = run_backfill(db, repo_dir)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
