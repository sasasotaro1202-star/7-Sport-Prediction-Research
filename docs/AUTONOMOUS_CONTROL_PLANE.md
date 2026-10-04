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

## Action-aware autonomous execution

The control plane also snapshots GitHub Actions state before deciding. It distinguishes:
- no run observed
- active run
- successful recent run
- stale run
- failed/timed-out run

The corresponding maintenance workflows can be re-dispatched only with bounded cooldowns and a current-main SHA guard.

Automatic responsibilities remain separated by owner:
- pre-event production heartbeat → production watchdog / pre-event prediction
- PIT historical expansion → fixed 00:47/09:47/18:47 UTC cadence
- production/data failure recovery → Production Failure Recovery
- research/source/scope maintenance → autonomous control plane
- model promotion → existing release gate only; never the control plane

The system records the selected action and dispatch decision in an append-only action log. A green control-plane run means reconciliation completed, not that model performance improved or production was promoted.
