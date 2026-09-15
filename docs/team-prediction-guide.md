# Team Prediction & Confidence Guide

## Purpose

This document is the shared operating contract for the seven-sport prediction system. The objective is future generalization and production reliability, not the highest historical backtest score.

## Seven sports

- Basketball
- Volleyball
- UFC
- RIZIN
- Tennis
- F1
- Valorant

## How a prediction is made

1. Build features using only information available at the prediction cutoff (PIT-safe).
2. Train/evaluate candidates chronologically with walk-forward OOS validation.
3. Keep the frozen holdout untouched during model selection.
4. Compare candidate models on predictive quality and calibration, not accuracy alone.
5. Prefer a stable model/ensemble over a fragile historical winner.
6. Publish a prediction only when data, model, PIT, and eligibility gates pass.
7. Preserve the exact prediction cutoff, dataset/model/config versions and provenance for auditability.

## Probability output

Every eligible prediction must expose probabilities, not just a winner label.

For a two-outcome event:

- Predicted side: the side with the highest calibrated probability.
- Side A probability: `0-100%`.
- Side B probability: `0-100%`.
- Probabilities must sum to approximately `100%` within the configured numerical tolerance.

For multi-entrant events such as F1, do not force the event into binary A/B semantics. Output the appropriate per-entrant probability distribution (for example, win probability) and validate that the semantics match the sport.

## Confidence is separate from probability

A high predicted probability is not automatically high confidence. Confidence should consider:

- calibrated probability and probability margin
- model agreement/diversity
- historical OOS performance
- calibration error
- data sufficiency
- missingness and freshness
- PIT/data-quality status
- distribution/regime drift
- uncertainty and sample size

Recommended user-facing classes:

- `HIGH`: strong, stable, well-supported prediction
- `MEDIUM`: usable prediction with material uncertainty
- `LOW`: model has a lean, but evidence is weak
- `PASS`: no actionable edge / confidence too low
- `INELIGIBLE`: prediction must not be produced because a required safety or data condition failed

## Separate the prediction list from the low-confidence list

The system should never hide uncertain events merely to make the ranking look stronger.

### Main ranking

Contains eligible events ordered by a stable production-oriented score. Show predicted outcome, all relevant probabilities, confidence class, and key data/model status.

### Low-confidence / watchlist

Contains events where a model can technically produce a probability but the evidence is weak, probabilities are close, models disagree, data quality is marginal, or drift/uncertainty is elevated.

### Ineligible

Contains events that should not receive a fabricated probability. Always record the exclusion reason.

## Important distinction

`Predicted winner` != `Recommended action`.

A model may predict A at 51.8%, while the production ranking classifies the event as `LOW` or `PASS`. This is intentional and protects against forced predictions.

## Sport-specific semantics

- Basketball / Volleyball / UFC / RIZIN / Tennis / Valorant: use the sport's valid match winner semantics.
- F1: use multi-entrant race semantics; do not treat the first two participants as the only possible winners.

## Reliability rules

- Green GitHub Actions status alone is never proof of a valid production result.
- Validate actual database partitions, schemas, row counts, outcomes, models, prediction files, metrics and hashes.
- Cache restore failures must not silently become empty datasets.
- Source outages may degrade coverage, but critical safety failures must fail closed.
- Never invent timestamps, winners, probabilities, historical availability, or missing source evidence.
- Never weaken a release gate solely to obtain a green run.

## Status vocabulary

Use these labels consistently:

`Requested` → `Started` → `Queued` → `Running` → `Completed` → `Success` / `Failed` / `Verified Success` / `Unknown` / `Blocked`

Use `Verified Success` only after checking the actual outputs and invariants, not merely the workflow conclusion.

## What teammates should look at first

1. `results/release_gate.json`
2. `results/quality_gate.json`
3. `results/prediction_eligibility.json`
4. `results/research/*.json`
5. prediction artifacts and model metadata
6. workflow logs/artifacts when diagnosing failures

If the release gate is blocked, do not bypass it. Identify the blocker, preserve evidence, fix the underlying issue, rerun, and verify.
