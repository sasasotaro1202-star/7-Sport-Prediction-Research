# Production completion standard

This document defines the release-completion standard for the nine-sport prediction system.

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

## Nine-sport semantics

Basketball, Volleyball, UFC, RIZIN, Tennis, and Valorant use appropriate event-outcome probability semantics for their competition format. F1 is multi-entrant: race-winner probabilities are represented per driver and must not be reduced to a binary A/B outcome merely to satisfy a generic schema.

## Competition universe and league-first priority

The system must not be limited to Asian Games or any fixed list of famous tournaments. It should systematically discover and classify materially available competitions across all nine sports.

**League and regular-season competitions are the highest production priority.** League coverage should receive the strongest attention to schedule completeness, historical depth, participant continuity, event timing, source freshness, PIT-safe information, outcome completeness, OOS continuity, and prediction freshness. Non-league coverage must not degrade league reliability or freshness.

The broader competition universe includes, where the sport supports them and reliable data exists:

- domestic leagues and regular seasons
- cups, playoffs, postseason, promotion/relegation playoffs, and qualifiers
- international club competitions and continental championships
- national-team and representative competitions, including Asian Games and equivalent regional events
- world championships, world cups, Olympic/major-games competitions, and other major international events
- U23/U21/U20/U19/U18/U17, junior, youth, academy, and developmental competitions
- university/college, high-school, Interhigh, school championships, and equivalents
- regional, invitational, challenger, exhibition, and other verified competitions

Every event should be classified when source evidence permits using competition level, age category, gender, team type, region, stage, season/year, and stable competition identity. Unknown values remain explicit; they are never guessed.

## Modeling separation

Do not blindly pool leagues, international events, national-team events, youth, university, and high-school competitions. Research may test pooled models with explicit competition taxonomy features, competition-stratified models, hierarchical/partial-pooling approaches, or separate models when populations, rules, formats, or data-generating processes differ.

Additional coverage is not automatically beneficial. A competition becomes production-eligible only after the same PIT, leakage, data-quality, calibration, robustness, and walk-forward OOS requirements are satisfied.

## PIT and historical integrity

Current web state is not historical truth. Historical features require evidence that the information was available by the prediction cutoff. Store and validate `published_at`, `updated_at`, `retrieved_at`, `available_at`, source/provider, source revision/hash, and dataset snapshot/version where available.

If historical availability cannot be established, the information is `UNKNOWN/UNVERIFIABLE` for PIT-sensitive modeling and must not be silently backfilled from current knowledge.

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

- league/regular-season coverage and completeness first
- broader competition taxonomy coverage
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

Coverage should be expanded systematically, not as one-off event additions. Include relevant international, representative, world, continental, Asian Games, age-group, youth, university, high-school, and regional competition families whenever reliable historical data and PIT-safe availability evidence exist. Pro, youth, student, reserve, academy, and national-team entities must not be silently mixed.

## Status vocabulary

Use only: `Requested`, `Started`, `Queued`, `Running`, `Completed`, `Success`, `Verified Success`, `Failed`, `Unknown`, `Blocked`.

Do not call a run complete merely because its workflow status is green.
