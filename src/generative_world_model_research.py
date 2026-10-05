from __future__ import annotations

"""Research-only bridge from PIT-safe temporal trajectories to future-world simulation.

This module deliberately stops at research evidence. It does not mutate production
probabilities, champion/challenger state, release gates, or frozen-holdout data.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from src.probabilistic_state_core import ScenarioMixture
from src.trajectory_intelligence_oos import (
    build_trajectory_cases,
    canonical_event_cases,
    chronological_event_folds,
    validate_snapshots,
)
from src.scenario_world_model import simulate_worlds, summarize_worlds

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_SPORTS = ("valorant", "basketball", "volleyball", "ufc", "rizin")
DEFAULT_HORIZONS = (120, 300, 600, 1200)
DEFAULT_K = 20
DEFAULT_WORLDS = 512
DEFAULT_SIM_CASES_PER_FOLD = 20


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def _metric(y: Sequence[int], p: Sequence[float]) -> dict[str, float | int]:
    yy = np.asarray(y, dtype=int)
    pp = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    if len(yy) == 0:
        raise ValueError("metric inputs must be non-empty")
    return {
        "logloss": float(
            -np.mean(yy * np.log(pp) + (1 - yy) * np.log(1 - pp))
        ),
        "brier": float(np.mean((pp - yy) ** 2)),
        "accuracy": float(np.mean((pp >= 0.5) == yy)),
        "n": int(len(yy)),
    }


def _fold_aggregate(metrics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(metrics)
    if not rows:
        return {"status": "NO_EVIDENCE"}
    return {
        "status": "OK",
        "folds": len(rows),
        "logloss_mean": float(np.mean([float(x["logloss"]) for x in rows])),
        "brier_mean": float(np.mean([float(x["brier"]) for x in rows])),
        "accuracy_mean": float(np.mean([float(x["accuracy"]) for x in rows])),
        "n_total": int(sum(int(x["n"]) for x in rows)),
        "logloss_std": float(np.std([float(x["logloss"]) for x in rows], ddof=1))
        if len(rows) > 1
        else 0.0,
    }


def _seed_for(*parts: Any) -> int:
    digest = hashlib.sha256(_json_dump(list(parts)).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _beta_draw(mean: float, concentration: float, rng: np.random.Generator) -> float:
    p = float(np.clip(mean, 1e-6, 1 - 1e-6))
    k = float(max(concentration, 2.0))
    return float(rng.beta(max(p * k, 1e-6), max((1.0 - p) * k, 1e-6)))


def simulate_uncertainty_worlds(
    probability: float,
    *,
    worlds: int = DEFAULT_WORLDS,
    seed: int = 0,
) -> dict[str, Any]:
    """Propagate parameter uncertainty into event outcomes without changing the mean."""
    p0 = float(probability)
    if not np.isfinite(p0) or not 0.0 <= p0 <= 1.0:
        raise ValueError("probability must be in [0,1]")

    scenarios = (
        ScenarioMixture("stable_state", 0.78, 0.78),
        ScenarioMixture("uncertain_state", 0.22, 0.22),
    )

    def parameter_sampler(scenario_id: str, rng: np.random.Generator) -> dict[str, float]:
        concentration = 96.0 if scenario_id == "stable_state" else 10.0
        return {"p": _beta_draw(p0, concentration, rng)}

    def initial_state_sampler(
        scenario_id: str, params: Mapping[str, float], rng: np.random.Generator
    ) -> Mapping[str, Any]:
        return {"success": 0, "failure": 0, "p": float(params["p"])}

    def transition_sampler(
        state: Mapping[str, Any],
        params: Mapping[str, float],
        step: int,
        rng: np.random.Generator,
    ):
        from src.scenario_world_model import Transition

        hit = bool(rng.random() < float(params["p"]))
        if hit:
            return Transition(
                {
                    "success": int(state["success"]) + 1,
                    "failure": int(state["failure"]),
                    "p": float(state["p"]),
                },
                "FOCAL_OUTCOME",
            )
        return Transition(
            {
                "success": int(state["success"]),
                "failure": int(state["failure"]) + 1,
                "p": float(state["p"]),
            },
            "OPPONENT_OUTCOME",
        )

    def terminal_predicate(state: Mapping[str, Any], step: int) -> bool:
        return step >= 1

    def outcome_function(state: Mapping[str, Any]) -> tuple[str, float]:
        margin = float(int(state["success"]) - int(state["failure"]))
        return ("A" if margin > 0 else "B"), margin

    worlds_out = simulate_worlds(
        scenarios,
        parameter_sampler=parameter_sampler,
        initial_state_sampler=initial_state_sampler,
        transition_sampler=transition_sampler,
        terminal_predicate=terminal_predicate,
        outcome_function=outcome_function,
        worlds=int(worlds),
        max_steps=1,
        seed=int(seed),
    )
    summary = summarize_worlds(worlds_out, focal_winner="A", tail_loss_margin=1.0)
    summary["baseline_probability"] = p0
    summary["simulation_probability_delta"] = float(
        summary["focal_win_probability"] - p0
    )
    summary["status"] = "RESEARCH_ONLY"
    return summary


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON: {path}")
    return payload


def _event_outcomes(path: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(path)
    # Accept either the canonical {event_id: {...}} form or a wrapper.
    if "outcomes" in payload and isinstance(payload["outcomes"], dict):
        payload = payload["outcomes"]
    return {
        str(k): dict(v)
        for k, v in payload.items()
        if isinstance(v, Mapping)
    }


def research_one_sport(
    sport: str,
    *,
    snapshots_path: Path,
    outcomes_path: Path,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    k: int = DEFAULT_K,
    worlds: int = DEFAULT_WORLDS,
    simulation_cases_per_fold: int = DEFAULT_SIM_CASES_PER_FOLD,
    min_train_events: int = 24,
    n_folds: int = 6,
) -> dict[str, Any]:
    snapshots_raw = _load_jsonl(snapshots_path)
    outcomes = _event_outcomes(outcomes_path)
    base = {
        "sport": sport,
        "engine_version": "generative-world-model-research-v1",
        "status": "BLOCKED",
        "promotion_status": "RESEARCH_ONLY_NO_AUTO_PROMOTION",
        "source_snapshot_file": str(snapshots_path),
        "source_outcome_file": str(outcomes_path),
        "pit_status": "UNKNOWN",
        "case_count": 0,
        "event_count": 0,
        "folds": [],
    }

    if not snapshots_raw:
        base["reason"] = "NO_TRAJECTORY_SNAPSHOT_ROWS"
        return base

    validation = validate_snapshots(snapshots_raw, mode="in_event")
    base["pit_status"] = "PASS" if validation["status"] == "PASS" else "PIT_INVALID_INPUT"
    base["pit_input_rows"] = int(validation["input_rows"])
    base["pit_valid_rows"] = int(validation["valid_rows"])
    base["pit_invalid_rows"] = int(validation["invalid_rows"])
    if validation["status"] != "PASS":
        base["reason"] = "PIT_INVALID_INPUT"
        base["pit_errors"] = validation["errors"][:25]
        return base

    built = build_trajectory_cases(
        validation["snapshots"],
        outcomes,
        horizons,
    )
    cases = canonical_event_cases(built["cases"], anchor_policy="earliest")
    base["case_count"] = int(len(cases))
    base["event_count"] = int(len({c.event_id for c in cases}))
    base["skipped_cases"] = built.get("skipped", [])[:50]

    if not cases:
        base["reason"] = "NO_COMPLETE_PIT_TRAJECTORY_CASES"
        return base

    folds = chronological_event_folds(
        cases,
        n_folds=int(n_folds),
        min_train_events=int(min_train_events),
    )
    if not folds:
        base["status"] = "BLOCKED"
        base["reason"] = "INSUFFICIENT_CHRONOLOGICAL_EVENT_FOLDS"
        return base

    case_by_id = {c.event_id: c for c in cases}
    horizon_results: dict[str, list[dict[str, Any]]] = {
        str(h): [] for h in cases[0].horizons_seconds
    }

    for fold in folds:
        train = [case_by_id[eid] for eid in fold["train_event_ids"]]
        test = [case_by_id[eid] for eid in fold["test_event_ids"]]
        memory = None
        try:
            from src.trajectory_intelligence_oos import EmpiricalTrajectoryMemory

            memory = EmpiricalTrajectoryMemory(k=int(k)).fit(train)
        except Exception as exc:
            base["folds"].append(
                {
                    "fold": int(fold["fold"]),
                    "status": "BLOCKED",
                    "reason": f"MEMORY_FIT_FAILED:{type(exc).__name__}",
                }
            )
            continue

        fold_payload: dict[str, Any] = {
            "fold": int(fold["fold"]),
            "train_event_count": len(train),
            "test_event_count": len(test),
            "status": "OK",
            "horizons": {},
        }

        # OOS scoring uses every canonical test event. Expensive world simulation
        # is intentionally bounded to a deterministic prefix for diagnostic cost.
        sim_test = test[: max(0, int(simulation_cases_per_fold))]
        sim_ids = {c.event_id for c in sim_test}

        for horizon in cases[0].horizons_seconds:
            hkey = str(horizon)
            preds: list[float] = []
            actuals: list[int] = []
            sims: list[dict[str, Any]] = []
            for case in test:
                pred = memory.predict(case.anchor_features, event_id=case.event_id)
                p = float(np.clip(pred["outcome_probability"][hkey], 1e-6, 1 - 1e-6))
                preds.append(p)
                actuals.append(int(case.outcome))
                if case.event_id in sim_ids:
                    sims.append(
                        {
                            "event_id": case.event_id,
                            "baseline_probability": p,
                            "world_summary": simulate_uncertainty_worlds(
                                p,
                                worlds=int(worlds),
                                seed=_seed_for(sport, fold["fold"], case.event_id, horizon),
                            ),
                        }
                    )
            score = _metric(actuals, preds)
            baseline = _metric(actuals, [0.5] * len(actuals))
            improvement = float(baseline["logloss"] - score["logloss"])
            horizon_results[hkey].append(
                {
                    "fold": int(fold["fold"]),
                    **score,
                    "baseline_half_logloss": float(baseline["logloss"]),
                    "logloss_improvement_vs_half": improvement,
                }
            )
            fold_payload["horizons"][hkey] = {
                **score,
                "logloss_improvement_vs_half": improvement,
                "simulation_sample": sims,
            }

        base["folds"].append(fold_payload)

    horizon_summary = {}
    for horizon, rows in horizon_results.items():
        horizon_summary[horizon] = {
            "oos": _fold_aggregate(rows),
            "fold_results": rows,
        }

    base["status"] = "READY_RESEARCH_ONLY"
    base["horizon_summary"] = horizon_summary
    base["research_conclusion"] = (
        "Simulation kernel executed only where complete PIT trajectory cases exist. "
        "World-model simulation is a distribution/uncertainty diagnostic; it is not "
        "production evidence and does not alter incumbent probabilities."
    )
    return base


def run(
    *,
    sports: Iterable[str] = ACTIVE_SPORTS,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    k: int = DEFAULT_K,
    worlds: int = DEFAULT_WORLDS,
    simulation_cases_per_fold: int = DEFAULT_SIM_CASES_PER_FOLD,
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "version": "generative-world-model-research-v1",
        "status": "READY_RESEARCH_ONLY",
        "promotion_status": "RESEARCH_ONLY_NO_AUTO_PROMOTION",
        "sports": {},
    }
    for sport in sports:
        s = str(sport).strip().lower()
        if s not in ACTIVE_SPORTS:
            output["sports"][s] = {
                "status": "BLOCKED",
                "reason": "SPORT_NOT_IN_ACTIVE_SCOPE",
            }
            continue
        out = research_one_sport(
            s,
            snapshots_path=ROOT / "results" / "research" / f"trajectory_snapshots_{s}.jsonl",
            outcomes_path=ROOT / "results" / "research" / f"trajectory_outcomes_{s}.json",
            horizons=horizons,
            k=k,
            worlds=worlds,
            simulation_cases_per_fold=simulation_cases_per_fold,
        )
        output["sports"][s] = out
    statuses = [str(v.get("status")) for v in output["sports"].values()]
    if any(x == "PIT_INVALID_INPUT" for x in statuses):
        output["status"] = "PIT_INVALID_INPUT"
    elif any(x == "READY_RESEARCH_ONLY" for x in statuses):
        output["status"] = "READY_RESEARCH_ONLY"
    elif statuses:
        output["status"] = "BLOCKED"
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worlds", type=int, default=DEFAULT_WORLDS)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--simulation-cases-per-fold", type=int, default=DEFAULT_SIM_CASES_PER_FOLD)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "results" / "research" / "generative_world_model_research.json",
    )
    args = parser.parse_args()
    if args.worlds <= 0 or args.k < 3 or args.simulation_cases_per_fold < 0:
        raise SystemExit("invalid simulation research parameters")
    report = run(
        worlds=args.worlds,
        k=args.k,
        simulation_cases_per_fold=args.simulation_cases_per_fold,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_json_dump(report) + "\n", encoding="utf-8")
    print(_json_dump(report))
    return 0 if report["status"] in {"READY_RESEARCH_ONLY", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
