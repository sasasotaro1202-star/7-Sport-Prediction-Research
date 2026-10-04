# 7-Sport-Prediction-Research — Project Instructions

## Mission
Five active production lanes: VALORANT, Basketball, Volleyball, UFC and RIZIN. Tennis, F1, Rugby and Boxing remain research-only/deferred until staged scope gates pass.
Optimize Future Generalization, case-level correctness, probabilistic quality, calibration, uncertainty, predictability awareness, robustness, PIT integrity, information value, selective prediction and operational reliability. Historical fit alone is not success.

## Every run
Re-check the latest GitHub HEAD/default branch, code/config, tests, workflows, Actions, artifacts, registries, production/champion/challenger state, current research/OOS/holdout evidence, failures and backlog. Prefer REUSE → REPAIR → INTEGRATE → TEST → VERIFY. Never rewrite past evidence to improve apparent results. Treat current HEAD as authoritative over prior chat results.

## Cross-sport data rule
All five active sports must use the same evidence discipline but sport-specific data semantics. Do not build a UFC-only feature process.
For each sport, actively research and compare:
identity strength, recent form/load, historical performance statistics, participant/entity profiles, team/roster context, competition/phase context, matchday intelligence, data/source quality and interactions.
Basketball and Volleyball are first-class active lanes: player/team/roster/season/statistical information must be collected when available and PIT-valid; lack of PIT evidence is recorded as a data limitation, not silently replaced.
VALORANT must consider team, player/map, roster, patch/map-pool and event-format context. UFC/RIZIN must consider fighter profile, physical attributes, prior fight statistics, weight/rules and opponent-adjusted form. Deferred sports use the same framework when they pass their own source/PIT gates.

## Feature pattern research
Never assume that more columns are better.
Generate multiple candidate information patterns, including family ablations, pair/triple family combinations, differential/rate/trend/interaction variants and all-available baselines. Evaluate patterns on identical chronological pre-holdout windows.
Use recent-period performance, fold dispersion and feature-count complexity as selection signals. A pattern is not adopted because it wins one fold or because it has more data.
Feature-pattern research is applied to every active sport, not selectively to one sport.

## Feature-pattern research
For every active sport, do not assume that the largest feature set is optimal. Explore multiple PIT-safe patterns across identity/strength, recent form/load, historical performance statistics, athlete/player profile, team/roster/availability, competition/event context, matchday intelligence, data-quality state and interactions.

The pattern search must vary at least:
family inclusion/exclusion, fine-grained statistic blocks, A/B/D encoding, short/medium/long history emphasis, summary-statistic variants, profile/roster inclusion, matchday inclusion, quality-awareness, and interaction inclusion.

Use multi-stage chronological pre-holdout screening with a broad structured candidate grid, then retest diverse winners with more than one model family. Record negative results, robustness, feature count/complexity, source dependence and compute cost. Frozen holdout is score-only and never used to choose a pattern.

Basketball, Volleyball, VALORANT, UFC and RIZIN must all use this common pattern-search framework with sport-specific feature priorities. Tennis, F1, Rugby and Boxing must retain compatible sport-specific schemas while deferred. Missing or unproven information remains UNKNOWN/UNVERIFIABLE and cannot be treated as evidence.

Pattern selection alone is never production authorization; downstream model OOS/WFO, calibration, robustness, frozen holdout, release and monitoring gates remain mandatory.

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
