from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "24h_marathon"
SCOPE = ROOT / "config" / "ACTIVE_SCOPE_9_SPORTS.json"
HARD_EXCLUDED = {"baseball", "soccer"}
STAGE_SPORTS = {1: "basketball", 2: "volleyball", 3: "ufc", 4: "rizin", 5: "valorant"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def active_sports() -> list[str]:
    cfg = json.loads(SCOPE.read_text(encoding="utf-8"))
    out = []
    for sport, entries in (cfg.get("active_scope") or {}).items():
        if sport in HARD_EXCLUDED:
            continue
        if isinstance(entries, list) and any(
            isinstance(e, dict) and str(e.get("status", "")).upper() == "TARGET"
            for e in entries
        ):
            out.append(str(sport))
    if not out:
        raise RuntimeError("no TARGET sports in canonical scope")
    return sorted(set(out))


def run(label: str, argv: list[str], timeout: int) -> dict:
    started = time.monotonic()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    print(f"24H_CMD_START {label}: {' '.join(argv)}", flush=True)
    try:
        p = subprocess.run(
            argv, cwd=ROOT, env=env, text=True,
            capture_output=True, timeout=timeout
        )
        if p.stdout:
            print(p.stdout[-10000:], flush=True)
        if p.stderr:
            print(p.stderr[-5000:], flush=True)
        status = "PASS" if p.returncode == 0 else "FAILED"
        return {
            "label": label, "argv": argv, "status": status,
            "returncode": p.returncode,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired:
        return {
            "label": label, "argv": argv, "status": "TIMEOUT",
            "returncode": None,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
    except Exception as exc:
        return {
            "label": label, "argv": argv, "status": "ERROR",
            "returncode": None,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "error": f"{type(exc).__name__}:{exc}",
        }


def collector(sport: str) -> list[tuple[str, list[str], int]]:
    if sport == "basketball":
        return [("collect_basketball", ["python", "-m", "src.basketball_cdn_backfill", "--official-only"], 1800)]
    if sport == "volleyball":
        return [("collect_volleyball", ["python", "-m", "src.volleyball_fivb_vis_backfill"], 2400)]
    if sport == "ufc":
        return [("collect_ufc", ["python", "-m", "src.ufc_api_backfill", "--limit", "200"], 1800)]
    if sport == "rizin":
        return [("collect_rizin", ["python", "-m", "src.public_history_backfill", "--sports", "rizin"], 1800)]
    if sport == "valorant":
        return [("collect_valorant", ["python", "-m", "src.public_history_backfill", "--sports", "valorant"], 1800)]
    raise RuntimeError(f"unsupported active sport: {sport}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, choices=range(1, 6), required=True)
    ap.add_argument("--minutes", type=float, default=282.0)
    ap.add_argument("--research-interval-minutes", type=float, default=90.0)
    args = ap.parse_args()

    sport = STAGE_SPORTS[args.stage]
    active = active_sports()
    if sport not in active or sport in HARD_EXCLUDED:
        raise RuntimeError(f"stage scope violation: {sport}; active={active}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    started = utcnow()
    deadline = time.monotonic() + args.minutes * 60
    commands: list[dict] = []
    critical: list[str] = []
    degraded: list[str] = []

    # Always establish a reproducible local schema before research.
    for label, argv in [
        ("compile_strict", ["python", "-m", "py_compile", "src/research_cycle_strict.py"]),
        ("pit_replay_compile", ["python", "-m", "py_compile", "src/pit_replay_builder.py"]),
        ("scope_guard", ["python", "-c", "import json; c=json.load(open('config/ACTIVE_SCOPE_9_SPORTS.json')); assert not ({'baseball','soccer'} & set(c.get('active_scope',{})))"]),
    ]:
        row = run(label, argv, 180)
        commands.append(row)
        if row["status"] != "PASS":
            critical.append(label)

    if not critical:
        for label, argv, timeout in collector(sport):
            row = run(label, argv, timeout)
            commands.append(row)
            if row["status"] != "PASS":
                degraded.append(label)

    iteration = 0
    last_research = 0.0
    while time.monotonic() < deadline - 12 * 60 and not critical:
        iteration += 1

        row = run(
            "pit_replay",
            ["python", "-m", "src.pit_replay_builder"],
            1800,
        )
        commands.append(row)
        if row["status"] != "PASS":
            degraded.append(row["label"])

        if last_research == 0.0 or time.monotonic() - last_research >= args.research_interval_minutes * 60:
            row = run(
                f"strict_oos_{sport}",
                ["python", "-m", "src.research_cycle_strict", "--sport", sport],
                2400,
            )
            commands.append(row)
            if row["status"] != "PASS":
                degraded.append(row["label"])
            last_research = time.monotonic()

        checkpoint = {
            "version": "24h-research-marathon-main-v1",
            "stage": args.stage,
            "sport": sport,
            "active_target_sports": active,
            "started_at_utc": started,
            "updated_at_utc": utcnow(),
            "iterations": iteration,
            "command_count": len(commands),
            "critical_failures": sorted(set(critical)),
            "degraded_tasks": sorted(set(degraded)),
            "hard_exclusions": sorted(HARD_EXCLUDED),
            "research_only": True,
            "production_model_touched": False,
        }
        (RESULTS / f"stage_{args.stage}_checkpoint.json").write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        remaining = deadline - time.monotonic()
        if remaining > args.research_interval_minutes * 60:
            time.sleep(args.research_interval_minutes * 60)

    final = {
        "version": "24h-research-marathon-main-v1",
        "stage": args.stage,
        "sport": sport,
        "active_target_sports": active,
        "started_at_utc": started,
        "finished_at_utc": utcnow(),
        "iterations": iteration,
        "command_count": len(commands),
        "critical_failures": sorted(set(critical)),
        "degraded_tasks": sorted(set(degraded)),
        "commands": commands,
        "status": "FAILED" if critical else ("DEGRADED" if degraded else "PASS"),
        "research_only": True,
        "production_model_touched": False,
        "hard_exclusions": sorted(HARD_EXCLUDED),
    }
    (RESULTS / f"stage_{args.stage}_final.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"24H_STAGE={args.stage} SPORT={sport} STATUS={final['status']} "
        f"ITERATIONS={iteration} COMMANDS={len(commands)}",
        flush=True,
    )
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
