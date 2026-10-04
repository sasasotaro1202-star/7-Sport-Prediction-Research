# 7-Sport-Prediction-Research — Project Instructions

## Mission
Five active production lanes: VALORANT, Basketball, Volleyball, UFC and RIZIN. Tennis, F1, Rugby and Boxing remain research-only/deferred until staged scope gates pass.
Optimize Future Generalization, case-level correctness, probabilistic quality, calibration, uncertainty, predictability awareness, robustness, PIT integrity, information value, selective prediction and operational reliability. Historical fit alone is not success.

## Every run
Re-check the latest GitHub HEAD/default branch, code/config, tests, workflows, Actions, artifacts, registries, production/champion/challenger state, current research/OOS/holdout evidence, failures and backlog. Prefer REUSE → REPAIR → INTEGRATE → TEST → VERIFY. Never rewrite past evidence to improve apparent results. Treat current HEAD as authoritative over prior chat results.

## Cross-sport data and feature-pattern rule
All nine project sports are covered by one evidence discipline and one feature-pattern research architecture:
VALORANT, Basketball, Volleyball, Tennis, UFC, RIZIN, F1, Rugby and Boxing.
Production/research/deferred status controls release eligibility, but never removes a sport from the research design.

For every sport, actively test these information families using sport-specific semantics:
identity/strength, recent form/load, historical performance statistics, participant/entity profile,
team/roster context, competition/phase/event context, matchday intelligence, data/source quality,
and derived interactions/representations.

Required pattern dimensions:
family on/off; leave-one-family-out; family subsets through structured multi-family combinations;
fine-grained statistic blocks; A/B/D; side-only/difference-only; signed and absolute difference;
relative/rate representations when semantically valid; short/medium/long history; mean/median/quantiles;
last/trend/EWMA; profile/roster/matchday/quality toggles; interaction toggles; sparse vs rich patterns.

Search stages:
1. broad structured screen on an early non-holdout prefix;
2. multi-model retest of diverse winners;
3. downstream full model/ensemble/router evaluation on later chronological OOS;
4. calibration, robustness and frozen-holdout verification.

The pattern selector must never see later OOS rows or frozen-holdout labels. Same-event snapshots remain clustered/dependent.
Never treat more columns as inherently better. Record negative patterns, source dependence, PIT/coverage,
stability, complexity and compute cost. Pattern screening alone cannot authorize ADOPTED/PRODUCTION.

Missing, delayed, unresolved or unproven information remains UNKNOWN/UNVERIFIABLE and is never converted into synthetic evidence.

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
