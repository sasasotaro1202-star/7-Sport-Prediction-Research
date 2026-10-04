# PROJECT_INSTRUCTIONS — 7-Sport-Prediction-Research

## Mission
Five active production lanes: VALORANT, Basketball, Volleyball, UFC and RIZIN. Tennis, F1, Rugby and Boxing remain research-only/deferred until staged scope gates pass.
Optimize Future Generalization, case-level correctness, probabilistic quality, calibration, uncertainty, predictability awareness, robustness, PIT integrity, information value, selective prediction and operational reliability. Historical fit alone is not success.

## Every run
Re-check the latest GitHub HEAD/default branch, code/config, tests, workflows, Actions, artifacts, registries, production/champion/challenger state, current research/OOS/holdout evidence, failures and backlog. Prefer REUSE → REPAIR → INTEGRATE → TEST → VERIFY. Never rewrite past evidence to make the current state look consistent. Treat current HEAD as authoritative over prior chat results.

## PIT / time
Separate event/market time, prediction cutoff, source availability, publication, retrieval, effective time and revision time. Only use information demonstrably available by cutoff. Unknown/unverifiable availability is fail-closed for production-quality OOS. A pre-event audit must not PASS a prediction generated after its own cutoff.

## Evaluation
Use chronological walk-forward OOS/WFO. Random splits are prohibited for temporal prediction. Separate candidate selection from final OOS. Frozen holdout is final evidence only and may not be tuned.

## Data integrity
Missing ≠ zero. Preserve explicit unavailable/unknown/delayed/not-yet-public/source-failed/malformed/not-applicable states. Preserve source lineage, snapshots, schema, revision behavior and identity history.

## Models / routing
Maintain simple baselines. Add challengers only for demonstrated incremental OOS value plus robustness. Specialist routing requires sufficient sample/folds/class coverage where relevant, calibration evidence and recent stability; otherwise fallback to broader validated scope.

## Calibration / uncertainty
Calibrate chronologically. Confidence ≠ predictability. Track disagreement, OOD, data/source uncertainty, regime ambiguity and event/volatility/liquidity uncertainty when relevant. Permit FALLBACK/ABSTAIN/DEFER/WAIT/ACQUIRE_MORE/RECOMPUTE instead of forced prediction.

## Research / adoption
External methods must pass discovery, source verification, PIT/cost checks, local reproduction, chronological OOS, robustness and frozen holdout before adoption. A candidate is never promoted from a single fold or external claim.

## Reliability / cost / security
Use checkpoint/resume, idempotency, bounded retry/backoff, watchdog/heartbeat, stale-run detection, deterministic writes, artifact preservation, concurrency control, recovery and rollback. Never hide failure. Prefer verified free/OSS/local/cache; unknown-cost or billing-risk services are not automatic dependencies. Never expose credentials.

## Completion
Green CI, generated artifacts or a completed workflow do not prove performance verification or production completion. Evidence must cover tests, PIT/leakage/meta-leakage, relevant universe/scope audits, chronological OOS/WFO, calibration, ablation, robustness, frozen holdout, artifact integrity, reproducibility, recovery, release gate, monitoring and rollback.

## Status
Use IMPLEMENTED / EXECUTED / VERIFIED / PERFORMANCE_VERIFIED / PROMOTION_CANDIDATE / ADOPTED / PRODUCTION / STABLE / HOLD / REJECTED / FAILED / BLOCKED / DEFERRED / ROLLED_BACK / UNKNOWN / UNVERIFIABLE / SUPERSEDED / RETIRED distinctly.

## Prediction timing / Experience
Automatic production scheduling is T-60-centered for the five active sports and runs every 15 minutes, covering the 45–75 minute guideline window. Heavy adaptive/shadow timing research is isolated from the scheduled lane. Explicit manual lead-times accept any positive integer with no upper bound and remain exact. PIT History Expansion runs only at the fixed 00:47, 09:47, and 18:47 UTC 9-hour epoch boundaries or by explicit manual dispatch; repository pushes do not enqueue PIT no-op runs. The production watchdog recovers a missed boundary, counts only scheduled/manual PIT executions, permits at most one PIT attempt per boundary window, and does not replace failure-specific recovery. Every prediction enters the Experience ledger; only verified mature outcomes may score it, and same-event revisions are not independent samples.

## Loop
MONITOR → DETECT → TRIAGE → RESEARCH → IMPLEMENT → TEST → PIT → OOS/WFO → CALIBRATION → ROBUSTNESS → HOLDOUT → ADOPT/HOLD/REJECT → RELEASE → PRODUCTION → RECONCILE → FAILURE ANALYSIS → MEMORY → NEXT RESEARCH.

## GitHub-native autonomous control plane

The detailed technical specification is tracked in `PROJECT_SOURCE.md`. When it conflicts with current runtime code, registry, or measured GitHub evidence, current GitHub state remains authoritative.

The repository also runs `.github/workflows/autonomous_control_plane.yml` every three hours and on manual dispatch. It reconciles current release/PIT/prediction/experience/route/reproducibility evidence, ranks the next action using the project research-priority principle, persists a deduplicated research queue and automation-health state, and may dispatch only allowlisted research workflows under active-run and cooldown guards.

Automatic model promotion is forbidden. PIT coverage repair does not bypass the fixed PIT-history cadence, and production heartbeat recovery remains owned by the existing production watchdog/pre-event workflow. Every autonomous write re-checks current `main` before push and fails closed on a concurrent branch update.

### Autonomous GitHub execution layer
The autonomous control plane is the operational orchestrator. Every three hours it snapshots the state of relevant GitHub Actions workflows, reconciles release/PIT/prediction/experience/route/reproducibility evidence, prioritizes the next action, and may dispatch only bounded allowlisted maintenance/research workflows. It may recover stale or failed source-feasibility, scope-autofill, runtime-health, safety-audit, and lane-audit jobs, and may launch bounded research when active model coverage is still incomplete.

Existing owners remain authoritative: the production watchdog owns pre-event heartbeat recovery; PIT History Expansion keeps its fixed 9-hour cadence; Production Failure Recovery owns failure-specific recovery. The control plane must not bypass these contracts.

Actions state is treated as evidence, not as success by existence. Missing or malformed evidence remains UNKNOWN/UNVERIFIABLE and is never converted to zero. Automatic model promotion, frozen-holdout tuning, and silent scope activation remain forbidden.

### PIT evidence automation hardening
The fixed PIT-history workflow now performs a strict B.LEAGUE exact-materialization step using only the already-registered research evidence, the exact commit-pinned source revision, and its conservative publication bound. Canonical event/participant resolution is required; zero exact rows is a hard failure, and no model/OOS/holdout/production promotion is implied by materialization.

The F1 OpenF1 historical backfill records HTTP status for fetch failures. A complete 401/403-only outage with zero ingested and zero skipped rows is classified as DEFERRED_PIT and written to results/f1_openf1_backfill.json; mixed, unknown, or partial failures remain fail-closed rather than being silently downgraded.

### Autonomous dispatch ordering safety
The control plane must reconcile and persist its current state before starting any autonomous maintenance/research workflow. After persistence, it captures the resulting main SHA and re-checks the remote main ref immediately before dispatch. Any concurrent main change fails closed; the next scheduled control cycle may retry. Dispatch is never keyed to the pre-persistence invocation SHA.

### Failure-memory-driven autonomous research
The control plane reads append-only `results/failure_memory.jsonl` each cycle, distinguishes recent recorded failures from missing/invalid evidence, and raises bounded research follow-up when failures occurred within the last 24 hours. Failure details are never inferred from absent fields. Production Failure Recovery remains the owner of failure-specific retry; the control plane only converts observed failures into research priority.

The Actions snapshot also monitors production, PIT History Expansion, Production Failure Recovery, Production Watchdog, Production Invariants, and Lightweight Regression as evidence-only workflows. Monitoring does not grant permission to dispatch or promote them.
