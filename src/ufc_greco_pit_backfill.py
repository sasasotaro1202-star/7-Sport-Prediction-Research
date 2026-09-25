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
PARSER_VERSION = "ufc-greco-pit-backfill-v1"
MIN_PIT_GAP_MINUTES = 60
STAT_FIELDS = {
    "sig_str": "SIG.STR.",
    "takedown": "TD",
    "sub_attempts": "SUB.ATT",
    "control_time": "CTRL",
}

def _norm(value: str | None) -> str:
    return " ".join(str(value or "").strip().casefold().split())

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
    text = str(value or "").strip().replace("—", "-")
    if not text or text in {"--", "---", "-"}:
        return None
    parts = text.split("of")
    if len(parts) != 2:
        return None
    try:
        landed, attempted = float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None
    if not (landed == landed and attempted == attempted):
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
    return x if x == x and abs(x) != float("inf") else None

def _parse_control(value: str | None) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"--", "---", "-"}:
        return None
    if ":" not in text:
        return _parse_float(text)
    parts = text.split(":")
    if len(parts) != 2:
        return None
    try:
        minutes, seconds = int(parts[0]), int(parts[1])
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
    lookup = {str(name).strip(): i for i, name in enumerate(header)}
    required = {"EVENT", "BOUT", "ROUND", "FIGHTER"} | set(STAT_FIELDS.values())
    missing = sorted(required - set(lookup))
    if missing:
        raise RuntimeError(f"upstream_header_missing:{','.join(missing)}")
    return lookup

def _parse_data_row(row: list[str], header: list[str]) -> dict | None:
    try:
        h = _header_map(header)
        if len(row) != len(header):
            return None
        event, bout, fighter = (str(row[h[k]]).strip() for k in ("EVENT", "BOUT", "FIGHTER"))
        round_no = _round_number(row[h["ROUND"]])
        if not event or not bout or not fighter or round_no is None:
            return None
        parsed = {
            "event": event, "event_key": _norm(event), "bout": bout, "bout_key": _norm(bout),
            "fighter": fighter, "fighter_key": _norm(fighter), "round": round_no,
        }
        for stat, field in STAT_FIELDS.items():
            raw = row[h[field]]
            if stat in {"sig_str", "takedown"}:
                value = _parse_fraction(raw)
            elif stat == "sub_attempts":
                value = _parse_float(raw)
                if value is not None and value < 0:
                    value = None
            else:
                value = _parse_control(raw)
            parsed[stat] = value
        return parsed
    except (IndexError, RuntimeError):
        return None

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
    out = []
    for line in raw.splitlines():
        if line.strip():
            sha, ts = line.split("\t", 1)
            out.append((sha.strip(), _parse_dt(ts.strip())))
    if not out:
        raise RuntimeError("upstream_stats_history_empty")
    return out

def _collect_first_numeric(repo_dir: Path):
    first, commits = {}, _iter_commits(repo_dir)
    rows_added = commits_with_additions = 0
    canonical_header = [
        "EVENT","BOUT","ROUND","FIGHTER","KD","SIG.STR.","SIG.STR. %",
        "TOTAL STR.","TD","TD %","SUB.ATT","REV.","CTRL","HEAD","BODY",
        "LEG","DISTANCE","CLINCH","GROUND",
    ]
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
            parsed = _parse_data_row(raw, canonical_header)
            if parsed is None:
                continue
            for stat in STAT_FIELDS:
                if parsed[stat] is None:
                    continue
                key = (parsed["event_key"], parsed["bout_key"], int(parsed["round"]), parsed["fighter_key"], stat)
                first.setdefault(key, {"commit": sha, "commit_time": commit_time, "value": parsed[stat]})
    return first, commits, rows_added, commits_with_additions

def _load_local_maps(con):
    event_map = defaultdict(list)
    for eid, competition, et in con.execute(
        "SELECT event_id, COALESCE(competition_id,''), event_time_utc FROM event WHERE sport='ufc' AND event_time_utc IS NOT NULL"
    ):
        try:
            event_map[(_parse_dt(et).date().isoformat(), _norm(competition))].append(str(eid))
        except Exception:
            pass
    participants = defaultdict(list)
    for pid, name in con.execute("SELECT participant_id, canonical_name FROM participant WHERE sport='ufc'"):
        if _norm(name):
            participants[_norm(name)].append(str(pid))
    event_participants = defaultdict(set)
    for eid, pid, side in con.execute(
        "SELECT event_id, participant_id, side FROM event_participant WHERE event_id IN (SELECT event_id FROM event WHERE sport='ufc') AND side IN ('A','B') AND participant_id IS NOT NULL"
    ):
        event_participants[str(eid)].add(str(pid))
    event_times = {}
    for eid, et in con.execute("SELECT event_id, event_time_utc FROM event WHERE sport='ufc' AND event_time_utc IS NOT NULL"):
        event_times[str(eid)] = _parse_dt(et)
    return event_map, participants, event_participants, event_times

def _candidate_groups(first, con):
    event_map, participants, event_participants, event_times = _load_local_maps(con)
    groups = defaultdict(dict)
    for (event_key, bout_key, round_no, fighter_key, stat), obs in first.items():
        groups[(event_key, bout_key, fighter_key, stat)][round_no] = obs
    candidates, skipped = [], 0
    for (event_key, bout_key, fighter_key, stat), rounds in groups.items():
        possible = [(date, eid) for (date, name), ids in event_map.items() if name == event_key for eid in ids]
        if len(possible) != 1:
            skipped += 1
            continue
        date, eid = possible[0]
        pids = participants.get(fighter_key, [])
        if len(pids) != 1 or pids[0] not in event_participants.get(eid, set()):
            skipped += 1
            continue
        required = set(range(1, max(rounds) + 1))
        if not required.issubset(rounds):
            skipped += 1
            continue
        avail_item = max((rounds[r] for r in required), key=lambda x: (x["commit_time"], x["commit"]))
        candidates.append({
            "event_id": eid, "event_date": date, "event_time": event_times[eid],
            "participant_id": pids[0], "fighter_key": fighter_key, "event_key": event_key,
            "bout_key": bout_key, "stat": stat, "rounds": sorted(required),
            "available_at": avail_item["commit_time"], "available_commit": avail_item["commit"],
        })
    unique = {}
    for row in candidates:
        key = (row["event_id"], row["participant_id"], row["stat"], tuple(row["rounds"]))
        old = unique.get(key)
        if old is None or (row["available_at"], row["available_commit"]) < (old["available_at"], old["available_commit"]):
            unique[key] = row
    return list(unique.values()), len(candidates), skipped

def _read_commit_rows(repo_dir: Path, sha: str):
    raw = _run(["git", "show", f"{sha}:{UPSTREAM_FILE}"], cwd=repo_dir)
    reader = csv.reader(io.StringIO(raw))
    try:
        header = next(reader)
    except StopIteration:
        raise RuntimeError(f"empty_upstream_stats_at:{sha}")
    rows = [parsed for row in reader if (parsed := _parse_data_row(row, header)) is not None]
    return rows, hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()

def _aggregate_commit_rows(rows, candidate):
    wanted = set(candidate["rounds"])
    matching = [
        r for r in rows
        if r["event_key"] == candidate["event_key"]
        and r["bout_key"] == candidate["bout_key"]
        and r["fighter_key"] == candidate["fighter_key"]
        and r["round"] in wanted
    ]
    by_round = {r["round"]: r for r in matching}
    if any(rn not in by_round for rn in wanted):
        return None
    sig = [by_round[rn]["sig_str"] for rn in candidate["rounds"]]
    td = [by_round[rn]["takedown"] for rn in candidate["rounds"]]
    subs = [by_round[rn]["sub_attempts"] for rn in candidate["rounds"]]
    ctrl = [by_round[rn]["control_time"] for rn in candidate["rounds"]]
    if any(v is None for v in sig + td + subs + ctrl):
        return None
    sig_total = float(sum(v[0] for v in sig))
    td_landed = float(sum(v[0] for v in td))
    td_attempted = float(sum(v[1] for v in td))
    sub_total = float(sum(subs))
    ctrl_total = float(sum(ctrl))
    return {
        "sig_str": sig_total,
        "takedown": td_landed,
        "td_pct": 0.0 if td_attempted == 0.0 else 100.0 * td_landed / td_attempted,
        "sub_attempts": sub_total,
        "control_time": ctrl_total,
    }

def _snapshot_id(commit, content_hash):
    return hashlib.sha256(f"{UPSTREAM_SOURCE}|{commit}|{content_hash}".encode()).hexdigest()[:32]

def _upsert_snapshot(con, commit, commit_time, content_hash):
    source_url = f"https://raw.githubusercontent.com/Greco1899/scrape_ufc_stats/{commit}/{UPSTREAM_FILE}"
    sid = _snapshot_id(commit, content_hash)
    con.execute(
        """
        INSERT OR REPLACE INTO source_snapshot(
            snapshot_id,sport,source,source_url,retrieved_at_utc,
            source_available_at_utc,event_time_utc,content_hash,
            parser_version,availability_status,provenance_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            sid, "ufc", UPSTREAM_SOURCE, source_url, utcnow(), commit_time.isoformat(),
            None, content_hash, PARSER_VERSION, "EXACT",
            json.dumps({
                "repository": UPSTREAM_SOURCE, "commit": commit,
                "commit_time_utc": commit_time.isoformat(), "file": UPSTREAM_FILE,
                "availability_basis": "public_git_commit_timestamp",
                "scope": "full immutable file snapshot at fixed commit",
                "non_claim": "commit time proves repository snapshot existence, not original UFCStats web-publication time",
            }, ensure_ascii=False),
        ),
    )
    return sid

def run_backfill(db_path: Path, repo_dir: Path) -> dict:
    first, commits, rows_added, commits_with_additions = _collect_first_numeric(repo_dir)
    with sqlite3.connect(db_path) as con:
        candidates, matched, skipped = _candidate_groups(first, con)
        by_commit = defaultdict(list)
        for c in candidates:
            by_commit[c["available_commit"]].append(c)
        commit_cache, verified, failed_content = {}, [], 0
        for commit, cs in sorted(by_commit.items()):
            if commit not in commit_cache:
                commit_cache[commit] = _read_commit_rows(repo_dir, commit)
            rows, content_hash = commit_cache[commit]
            for candidate in cs:
                aggregate = _aggregate_commit_rows(rows, candidate)
                if aggregate is None:
                    failed_content += 1
                    continue
                candidate = dict(candidate)
                candidate["aggregate"] = aggregate
                candidate["content_hash"] = content_hash
                verified.append(candidate)
        commit_times = {sha: ts for sha, ts in commits}
        snapshots, snapshot_seen, inserted = 0, {}, 0
        touched_events = set()
        for candidate in verified:
            commit = candidate["available_commit"]
            sid_key = f"{commit}|{candidate['content_hash']}"
            sid = snapshot_seen.get(sid_key)
            if sid is None:
                sid = _upsert_snapshot(con, commit, commit_times[commit], candidate["content_hash"])
                snapshot_seen[sid_key] = sid
                snapshots += 1
            source_url = f"https://raw.githubusercontent.com/Greco1899/scrape_ufc_stats/{commit}/{UPSTREAM_FILE}"
            for stat_name, value in candidate["aggregate"].items():
                stat_id = hashlib.sha256(
                    f"ufc-greco-pit|{candidate['event_id']}|{candidate['participant_id']}|{stat_name}|{commit}|{value}".encode()
                ).hexdigest()[:32]
                con.execute(
                    """
                    INSERT OR REPLACE INTO match_stats(
                        stat_id,event_id,participant_id,team_id,sport,
                        observed_at_utc,effective_at_utc,stat_name,value_num,
                        value_text,unit,source,source_url,quality_status,confidence
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        stat_id, candidate["event_id"], candidate["participant_id"], None, "ufc",
                        utcnow(), candidate["event_time"].isoformat(), stat_name, float(value),
                        str(value), "seconds" if stat_name == "control_time" else None,
                        UPSTREAM_SOURCE, source_url, "EXACT", 1.0,
                    ),
                )
                inserted += 1
                touched_events.add(candidate["event_id"])
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
        "candidate_groups_failed_snapshot_content": failed_content,
        "source_snapshots_created": snapshots,
        "inserted_stat_rows": inserted,
        "touched_local_events": len(touched_events),
        "production_model_changed": False,
        "provenance_status": "EXACT_FIXED_GIT_SNAPSHOT",
        "pit_rule": f"source_available_at_utc <= prediction_cutoff; minimum_gap={MIN_PIT_GAP_MINUTES}m",
        "caution": "Public Git commit timestamp is used as a conservative availability bound; it is not claimed as the original UFCStats web publication timestamp.",
    }

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--upstream-dir", default=None)
    ap.add_argument("--output", default=str(ROOT / "results/ufc_greco_pit_backfill.json"))
    args = ap.parse_args()
    db_path = Path(args.db)
    if not db_path.is_file():
        raise SystemExit(f"FAIL_CLOSED_DB_MISSING:{db_path}")
    temp = None
    if args.upstream_dir:
        repo_dir = Path(args.upstream_dir)
    else:
        temp = ROOT / "results/.tmp-ufc-greco-upstream"
        if temp.exists():
            import shutil
            shutil.rmtree(temp)
        repo_dir = temp
    try:
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        if not repo_dir.exists():
            _run(["git", "clone", "--filter=blob:none", "--no-checkout", UPSTREAM_REPO, str(repo_dir)])
        report = run_backfill(db_path, repo_dir)
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        if temp is not None:
            import shutil
            shutil.rmtree(temp, ignore_errors=True)

if __name__ == "__main__":
    raise SystemExit(main())
