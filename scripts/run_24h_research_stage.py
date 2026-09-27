from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "24h_marathon"
ACTIVE_SCOPE = ROOT / "config" / "ACTIVE_SCOPE_9_SPORTS.json"
HARD_EXCLUDED = {"baseball", "soccer"}

STAGE_SPORTS = {
    1: "basketball",
    2: "volleyball",
    3: "ufc",
    4: "rizin",
    5: "valorant",
    6: "integrity",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_active() -> list[str]:
    cfg = json.loads(ACTIVE_SCOPE.read_text(encoding="utf-8"))
    sports = []
    for sport, entries in (cfg.get("active_scope") or {}).items():
        if sport in HARD_EXCLUDED:
            continue
        if isinstance(entries, list) and any(
            isinstance(e, dict) and str(e.get("status", "")).upper() == "TARGET"
            for e in entries
        ):
            sports.append(str(sport))
    if not sports:
        raise RuntimeError("canonical active scope resolved to zero TARGET sports")
    return sorted(set(sports))


def run_cmd(label: str, argv: list[str], timeout: int | None = None) -> dict:
    started = time.monotonic()
    print(f"MARATHON_CMD_START label={label} argv={' '.join(argv)}", flush=True)
    try:
        p = subprocess.run(
            argv,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            env={**__import__("os").environ, "PYTHONPATH": str(ROOT)},
        )
        if p.stdout:
            print(p.stdout[-12000:], flush=True)
        if p.stderr:
            print(p.stderr[-6000:], flush=True)
        row = {
            "label": label,
            "argv": argv,
            "returncode": p.returncode,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "status": "PASS" if p.returncode == 0 else "FAILED",
        }
    except subprocess.TimeoutExpired as exc:
        if exc.stdout:
            print(str(exc.stdout)[-12000:], flush=True)
        if exc.stderr:
            print(str(exc.stderr)[-6000:], flush=True)
        row = {
            "label": label,
            "argv": argv,
            "returncode": None,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "status": "TIMEOUT",
        }
    except Exception as exc:
        row = {
            "label": label,
            "argv": argv,
            "returncode": None,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "status": "ERROR",
            "error": f"{type(exc).__name__}:{exc}",
        }
    print(
        f"MARATHON_CMD_END label={label} status={row['status']} "
        f"returncode={row.get('returncode')}",
        flush=True,
    )
    return row


def collection_commands(sport: str) -> list[tuple[str, list[str], int]]:
    if sport == "basketball":
        return [(
            "collect_basketball",
            ["python", "-m", "src.basketball_cdn_backfill", "--official-only"],
            1800,
        )]
    if sport == "volleyball":
        return [(
            "collect_volleyball",
            ["python", "-m", "src.volleyball_fivb_vis_backfill"],
            2400,
        )]
    if sport == "ufc":
        return [(
            "collect_ufc",
            ["python", "-m", "src.ufc_api_backfill", "--limit", "200"],
            1800,
        )]
    if sport == "rizin":
        return [(
            "collect_rizin",
            ["python", "-m", "src.public_history_backfill", "--sports", "rizin"],
            1800,
        )]
    if sport == "valorant":
        return [
            (
                "collect_valorant_history",
                ["python", "-m", "src.public_history_backfill", "--sports", "valorant"],
                1800,
            ),
            (
                "collect_valorant_provenance",
                ["python", "-m", "src.valorant_git_provenance"],
                1200,
            ),
        ]
    return []


def lightweight_cycle(stage: int, sport: str | None, iteration: int, command_log: list[dict]) -> None:
    command_log.append(
        run_cmd(
            "scope_discovery",
            ["python", "scripts/discover_scope_expansion.py", "--output", str(RESULTS / f"stage_{stage}_scope_{iteration}.json")],
            timeout=120,
        )
    )
    command_log.append(
        run_cmd(
            "competition_scope_tests",
            ["python", "scripts/test_competition_scope_frontier.py"],
            timeout=120,
        )
    )
    command_log.append(
        run_cmd(
            "competition_classifier_tests",
            ["python", "scripts/test_competition_scope_classifier.py"],
            timeout=120,
        )
    )
    command_log.append(
        run_cmd(
            "source_probe",
            ["python", "-m", "src.cross_sport_source_probe"],
            timeout=600,
        )
    )
    command_log.append(
        run_cmd(
            "shadow_ingest",
            ["python", "-m", "src.cross_sport_shadow_ingest"],
            timeout=600,
        )
    )
    if sport and sport != "integrity":
        command_log.append(
            run_cmd(
                "source_usage_audit",
                ["python", "-m", "src.source_usage_audit", "--sport", sport, "--output", str(RESULTS / f"stage_{stage}_{sport}_usage_{iteration}.json")],
                timeout=900,
            )
        )


def research_once(sport: str, command_log: list[dict]) -> None:
    command_log.append(
        run_cmd(
            f"strict_oos_{sport}",
            ["python", "-m", "src.research_cycle_strict", "--sport", sport],
            timeout=2400,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, choices=range(1, 7), required=True)
    parser.add_argument("--minutes", type=float, default=238.0)
    parser.add_argument("--interval-minutes", type=float, default=45.0)
    args = parser.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    active = load_active()
    sport = STAGE_SPORTS[args.stage]
    if sport != "integrity" and sport not in active:
        raise RuntimeError(f"stage sport {sport} is not in canonical TARGET scope: {active}")
    if sport in HARD_EXCLUDED:
        raise RuntimeError(f"hard-excluded sport reached marathon stage: {sport}")

    started_at = utcnow()
    deadline = time.monotonic() + args.minutes * 60
    command_log: list[dict] = []
    iterations = 0
    critical_failures = []
    degraded = []

    # Mandatory initial integrity checks before any data work.
    for label, argv in (
        ("scope_discovery_tests", ["python", "scripts/test_scope_expansion_discovery.py"]),
        ("cross_sport_data_layer_tests", ["python", "scripts/test_cross_sport_data_layer.py"]),
        ("source_usage_audit_tests", ["python", "scripts/test_source_usage_audit.py"]),
    ):
        row = run_cmd(label, argv, timeout=180)
        command_log.append(row)
        if row["status"] != "PASS":
            critical_failures.append(label)

    if not critical_failures and sport != "integrity":
        for label, argv, timeout_s in collection_commands(sport):
            row = run_cmd(label, argv, timeout=timeout_s)
            command_log.append(row)
            if row["status"] not in {"PASS"}:
                degraded.append(label)

    last_research = 0
    while time.monotonic() < deadline - 12 * 60:
        iterations += 1
        lightweight_cycle(args.stage, sport if sport != "integrity" else None, iterations, command_log)

        if sport != "integrity" and (last_research == 0 or time.monotonic() - last_research >= 90 * 60):
            row_count_before = len(command_log)
            research_once(sport, command_log)
            last_research = time.monotonic()
            for row in command_log[row_count_before:]:
                if row["status"] != "PASS":
                    degraded.append(row["label"])

        for row in command_log[-8:]:
            if row["label"].endswith("_tests") and row["status"] != "PASS":
                critical_failures.append(row["label"])

        checkpoint = {
            "version": "24h-research-marathon-v1",
            "stage": args.stage,
            "stage_sport": sport,
            "active_target_sports": active,
            "started_at_utc": started_at,
            "updated_at_utc": utcnow(),
            "iterations": iterations,
            "command_count": len(command_log),
            "critical_failures": sorted(set(critical_failures)),
            "degraded_tasks": sorted(set(degraded)),
            "research_only": True,
            "production_model_touched": False,
        }
        (RESULTS / f"stage_{args.stage}_checkpoint.json").write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        if critical_failures:
            break
        remaining = deadline - time.monotonic()
        if remaining > args.interval_minutes * 60:
            time.sleep(args.interval_minutes * 60)

    final = {
        "version": "24h-research-marathon-v1",
        "stage": args.stage,
        "stage_sport": sport,
        "active_target_sports": active,
        "started_at_utc": started_at,
        "finished_at_utc": utcnow(),
        "iterations": iterations,
        "command_count": len(command_log),
        "critical_failures": sorted(set(critical_failures)),
        "degraded_tasks": sorted(set(degraded)),
        "commands": command_log,
        "status": "FAILED" if critical_failures else ("DEGRADED" if degraded else "PASS"),
        "research_only": True,
        "production_model_touched": False,
        "hard_exclusions": sorted(HARD_EXCLUDED),
    }
    (RESULTS / f"stage_{args.stage}_final.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"MARATHON_STAGE={args.stage} SPORT={sport} STATUS={final['status']} "
        f"ITERATIONS={iterations} COMMANDS={len(command_log)}",
        flush=True,
    )
    return 1 if critical_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
