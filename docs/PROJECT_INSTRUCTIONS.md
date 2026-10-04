# 7-Sport-Prediction-Research — Project Instructions

## Mission
Five active production lanes: VALORANT, Basketball, Volleyball, UFC and RIZIN. Tennis, F1, Rugby and Boxing remain research-only/deferred until staged scope gates pass.
Optimize Future Generalization, case-level correctness, probabilistic quality, calibration, uncertainty, predictability awareness, robustness, PIT integrity, information value, selective prediction and operational reliability. Historical fit alone is not success.

## Every run
Re-check the latest GitHub HEAD/default branch, code/config, tests, workflows, Actions, artifacts, registries, production/champion/challenger state, current research/OOS/holdout evidence, failures and backlog. Prefer REUSE → REPAIR → INTEGRATE → TEST → VERIFY. Never rewrite past evidence to improve apparent results. Treat current HEAD as authoritative over prior chat results.

## Cross-sport data rule
All nine project sports are covered by one evidence discipline and one feature-pattern research architecture:
VALORANT, Basketball, Volleyball, UFC, RIZIN, Tennis, F1, Rugby and Boxing.
Production/deferred status affects whether a sport can currently train or release, but never removes it from the research design.

For every sport, actively test:
identity/strength, recent form/load, historical performance statistics, participant/entity profile, team/roster context, competition/phase/event context, matchday intelligence, data/source quality and derived interactions.
Use sport-specific semantics and source availability; never assume one universal feature recipe.

## Feature-pattern research
For all nine sports, never assume that the largest feature set is optimal.

The search must cover:
family inclusion/exclusion; leave-one-family-out controls; single/pair/triple/quadruple family subsets; fine-grained statistic blocks; A/B/D encodings; side-only vs difference-only; short/medium/long history; mean/median/quantile/last/trend/EWMA summaries; profile and roster toggles; matchday toggles; quality-aware vs quality-blind variants; interaction variants; relative/rate representations; and complexity/sparsity alternatives.

Use a staged search:
1. broad structured screening on an early training prefix;
2. multi-model retest of diverse winners;
3. downstream full model/ensemble/routing evaluation on later chronological OOS;
4. robustness, calibration and frozen-holdout verification.

Pattern selection must not inspect the later OOS evaluation rows or frozen holdout. Record negative results, source dependence, PIT coverage, stability, complexity and compute cost.

Basketball, Volleyball, VALORANT, UFC, RIZIN, Tennis, F1, Rugby and Boxing all use this architecture. Sport-specific information is added only when actually available and PIT-valid; deferred status does not authorize unproven data.

Missing, delayed, unresolved or unproven information remains UNKNOWN/UNVERIFIABLE and cannot be converted into synthetic evidence.

Pattern selection alone is never production authorization; all downstream OOS/WFO, robustness, calibration, frozen-holdout, release and monitoring gates remain mandatory.

## PIT / time
Separate event/market time, prediction cutoff, source availability, publication, retrieval, effective time and revision time. Only use information demonstrably available by cutoff. Unknown/unverifiable availability is fail-closed for production-quality OOS. A pre-event audit must not PASS a prediction generated after its own cutoff. Same-event snapshots at different cutoffs are dependent observations and are evaluated as event clusters.

## Identity / history
Canonicalize participant/team/competition/event identity. Fuzzy matching is candidate generation only. Preserve roster state, club/national/youth/reserve and gender/category boundaries. Participant and team history may become predictive only when identity is resolved, effective time is before the cutoff and an exact source-availability path proves PIT.

## Evaluation
Use chronological walk-forward OOS/WFO. Random splits are prohibited for temporal prediction. Separate pattern screening, model selection and final evidence. Frozen holdout is final score-only evidence and must not tune feature patterns, models, calibration or thresholds.

## Data integrity
Missing ≠ zero. Preserve unavailable/unknown/delayed/not-yet-public/source-failed/malformed/not-applicable states. Preserve source lineage, snapshots, schema, revision behavior and identity history.

## Models / routing
Maintain simple baselines. Add challengers only for demonstrated incremental OOS value plus robustness. Specialist routing requires sufficient sample/folds/class coverage, calibration evidence and recent stability; otherwise fallback to broader validated scope.

## Calibration / uncertainty
Calibrate chronologically. Confidence ≠ predictability. Track disagreement, OOD, data/source uncertainty, regime ambiguity and event-specific uncertainty. Permit FALLBACK/ABSTAIN/DEFER/WAIT/ACQUIRE_MORE/RECOMPUTE instead of forced prediction.

## Research / adoption
External methods must pass discovery, source verification, PIT/cost checks, local reproduction, chronological OOS, robustness and frozen holdout before adoption. A candidate is never promoted from a single fold, a single competition, or an external claim.

## Reliability / cost / security
Use checkpoint/resume, idempotency, bounded retry/backoff, watchdog/heartbeat, stale-run detection, deterministic writes, artifact preservation, concurrency control, recovery and rollback. Never hide failure. Prefer verified free/OSS/local/cache; unknown-cost or billing-risk services are not automatic dependencies. Never expose credentials.

## Completion
Green CI, generated artifacts or a completed workflow do not prove performance verification or production completion. Evidence must cover tests, PIT/leakage/meta-leakage, relevant universe/scope audits, feature-family/pattern ablation, chronological OOS/WFO, calibration, robustness, frozen holdout, artifact integrity, reproducibility, recovery, release gate, monitoring and rollback.

## Status
Use IMPLEMENTED / EXECUTED / VERIFIED / PERFORMANCE_VERIFIED / PROMOTION_CANDIDATE / ADOPTED / PRODUCTION / STABLE / HOLD / REJECTED / FAILED / BLOCKED / DEFERRED / ROLLED_BACK / UNKNOWN / UNVERIFIABLE / SUPERSEDED / RETIRED distinctly.

## Prediction timing / Experience
Automatic production scheduling is T-60-centered for the five active sports and runs every 15 minutes, covering the 45–75 minute guideline window. Heavy adaptive/shadow timing research is isolated from the scheduled lane. Explicit manual lead-times accept any positive integer with no upper bound and remain exact. PIT History Expansion runs only at the fixed 00:47, 09:47, and 18:47 UTC 9-hour epoch boundaries or by explicit manual dispatch; repository pushes do not enqueue PIT no-op runs. The production watchdog recovers a missed boundary, counts only scheduled/manual PIT executions, permits at most one PIT attempt per boundary window, and does not replace failure-specific recovery. Every prediction enters the Experience ledger; only verified mature outcomes may score it, and same-event revisions are not independent samples.

## Loop
MONITOR → DETECT → TRIAGE → RESEARCH → IMPLEMENT → TEST → PIT → PATTERN_SCREEN → OOS/WFO → CALIBRATION → ROBUSTNESS → HOLDOUT → ADOPT/HOLD/REJECT → RELEASE → PRODUCTION → RECONCILE → FAILURE ANALYSIS → MEMORY → NEXT RESEARCH.
