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

## GitHub-side autonomous next-action control
The repository also runs `.github/workflows/autonomous_next_action_controller.yml` hourly and on manual dispatch. It is a bounded orchestration layer, not a production/model promotion mechanism: it verifies the current `main` SHA, checks the canonical five-sport scope, treats stale release/quality reports as untrusted, stops on three recent production/data failures, and dispatches at most one existing research workflow within a cooldown window. It may select `scope_autofill.yml` when fresh gate evidence shows active-scope/PIT/model coverage deficits; otherwise it selects `autonomous_research_sweep.yml`. It never changes scope, model artifacts, probabilities, targets, timing policy, OOS/holdout evidence, or production state itself.

## Prediction timing / Experience
Automatic production scheduling is T-60-centered for the five active sports and runs every 15 minutes, covering the 45–75 minute guideline window. Heavy adaptive/shadow timing research is isolated from the scheduled lane. Explicit manual lead-times accept any positive integer with no upper bound and remain exact. PIT History Expansion runs only at the fixed 00:47, 09:47, and 18:47 UTC 9-hour epoch boundaries or by explicit manual dispatch; repository pushes do not enqueue PIT no-op runs. The production watchdog recovers a missed boundary, counts only scheduled/manual PIT executions, permits at most one PIT attempt per boundary window, and does not replace failure-specific recovery. Every prediction enters the Experience ledger; only verified mature outcomes may score it, and same-event revisions are not independent samples.

## Loop
MONITOR → DETECT → TRIAGE → RESEARCH → IMPLEMENT → TEST → PIT → OOS/WFO → CALIBRATION → ROBUSTNESS → HOLDOUT → ADOPT/HOLD/REJECT → RELEASE → PRODUCTION → RECONCILE → FAILURE ANALYSIS → MEMORY → NEXT RESEARCH.
