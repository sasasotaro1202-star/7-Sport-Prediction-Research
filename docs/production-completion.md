# Production completion standard

This document defines the release-completion standard for the seven-sport prediction system.

## Completion is evidence-based

A green GitHub Actions workflow is not sufficient. A run is `Verified Success` only after the produced database, manifests, models, predictions, metrics, audits, and hashes have been checked.

## Prediction contract

Every eligible prediction must expose, in a human-readable form:

- event identity and competition
- canonical team/player/driver names
- prediction timestamp and PIT cutoff
- predicted outcome
- probability for every supported outcome
- confidence: `HIGH`, `MEDIUM`, or `LOW`
- action state: `PRIMARY`, `SECONDARY`, or `PASS`
- model version, feature version, dataset snapshot/hash
- data quality and eligibility state

If evidence is insufficient, the system must emit `INELIGIBLE` rather than fabricate a probability.

`prediction` and `decision` remain separate. A model can identify the most probable outcome while the decision layer assigns `PASS` when confidence, calibration, robustness, or data quality is insufficient.

## Seven-sport semantics

Basketball, Volleyball, UFC, RIZIN, Tennis, and Valorant use appropriate event-outcome probability semantics for their competition format. F1 is multi-entrant: race-winner probabilities are represented per driver and must not be reduced to a binary A/B outcome merely to satisfy a generic schema.

## Reliability contract

Collectors must use bounded retries/backoff and preserve the last-known-good cache. Corrupt, empty, missing, or schema-invalid partitions must never silently become empty production datasets. Recovery may retry or use a validated prior cache, but critical integrity/PIT failures must fail closed and block publication.

Production publication requires all applicable release gates to pass. A partial/degraded run may be useful for diagnostics or research but must not be represented as a complete production release.

## Quality priorities

The optimization order is:

1. future generalization
2. leakage/PIT prevention
3. overfit prevention
4. OOS performance
5. stability
6. calibration
7. robustness
8. data quality
9. reliability
10. efficiency
11. cost
12. historical peak

No metric, coverage count, or runtime improvement may be obtained by weakening leakage controls, inventing historical timestamps/results, silently merging identities, or bypassing release gates.

## Verification checklist

Before declaring the system complete, verify for every sport:

- source provenance and historical availability timestamps
- canonical identity resolution
- nonempty and integrity-checked data
- event/outcome coverage appropriate to sport semantics
- PIT replay and leakage audit
- walk-forward OOS results
- frozen blind/holdout results
- calibration and uncertainty
- accepted champion model metadata including training cutoff
- prediction probability validity
- confidence/abstention behavior
- drift/robustness checks
- reproducibility metadata and hashes
- artifact persistence
- rollback/recovery path
- final release gate

## International and developmental competitions

Coverage should be expanded systematically to relevant world championships, Asian Games, continental competitions, national-team events, U18/U20/U23 and other youth categories, university/high-school competitions, and major regional competitions when reliable historical data and PIT-safe availability evidence exist. Pro, youth, student, reserve, academy, and national-team entities must not be silently mixed.

## Status vocabulary

Use only: `Requested`, `Started`, `Queued`, `Running`, `Completed`, `Success`, `Failed`, `Verified Success`, `Unknown`, `Blocked`.

Do not call a run complete merely because its workflow status is green.
