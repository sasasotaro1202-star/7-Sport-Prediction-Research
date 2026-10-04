# Autonomous Research Control Plane

The control plane is a GitHub-native orchestration layer for the existing prediction/research system. It does not replace the current production workflow, release gate, watchdog, PIT cadence, or research engines.

## What it does

Every three hours, and on manual dispatch, it:

1. Reads current checked-in evidence: release gate, quality gate, future predictions, experience summary, route/timing registries, reproducibility manifest, and dual-learning state.
2. Scores research and operations gaps using the project priority principle: Expected Impact × Evidence Gap × Failure Relevance × Generalization Potential × Information Value ÷ Cost.
3. Records the highest-priority action in an append-only research queue.
4. Separates the highest-priority action from the highest-priority safe automatic dispatch. Fixed PIT cadence and existing watchdog ownership are respected.
5. May automatically dispatch only the allowlisted research workflows, with active-run and cooldown guards.
6. Persists deterministic control-plane and automation-health state with GitHub SHA provenance.

## Safety boundaries

Model promotion is never automatic.

The control plane never tunes or rewrites a frozen holdout.

PIT coverage repair is queued, not used to bypass the repository's fixed PIT-history cadence.

The production heartbeat remains owned by the existing production watchdog/pre-event workflow.

Only autonomous_research_sweep.yml and 24h_autonomous_research.yml are eligible for automatic dispatch.

The persistence step re-checks main before pushing. A concurrent main-branch update causes a visible failure instead of overwriting newer state.

Repeated identical queue entries are deduplicated by deterministic fingerprint.

## Status semantics

A control-plane run being green proves only that reconciliation and safety checks completed. It does not imply PERFORMANCE_VERIFIED, ADOPTED, PRODUCTION, or STABLE.

Research outputs remain subject to the existing chronological OOS, PIT, calibration, robustness, frozen-holdout, reproducibility, and release gates.
