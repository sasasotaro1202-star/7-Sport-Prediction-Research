# Autonomous Completion & Reliability Protocol

## Objective

Optimize for real-world production robustness rather than in-sample performance or a green CI badge. The system should become more accurate, better calibrated, more reproducible, and faster **without weakening point-in-time (PIT) safety**.

## Non-negotiable production rules

1. **Chronological OOS only.** Random train/test splits are not acceptable for model selection.
2. **PIT before tuning.** A feature is usable only when its value and source availability are demonstrably known by the prediction cutoff.
3. **Frozen holdout.** The final production artifact must exclude the frozen holdout from fitting. Holdout results are used for acceptance, not optimization.
4. **Calibration matters.** Track log loss, Brier score, accuracy, and ECE. A probability forecast must be treated as a probability forecast, not merely a class label.
5. **Incumbent protection.** A challenger is not promoted merely because it is newer; it must clear the documented OOS/holdout gate.
6. **Missingness is information.** Missing, stale, unverifiable, or conflicting source data must reduce eligibility/coverage rather than be silently synthesized.
7. **Source outages degrade coverage, never truth.** Retry transient failures, reconcile independent sources where possible, and fail closed when the resulting dataset is unsafe.
8. **Identity stability.** Team/player/competitor normalization must be deterministic and versioned so historical entities do not silently split or merge.
9. **Reproducibility.** Every promoted artifact records its model version, feature version, training cutoff, dataset hash, and Git commit.
10. **Efficiency comes after safety.** Cache stable historical data, parallelize independent collectors, and avoid unnecessary recomputation, but never trade away PIT checks for speed.

## External implementation patterns incorporated

Public sports/time-series projects reviewed for transferable patterns include walk-forward research, purge/embargo safeguards, probability calibration challengers, leakage-aware pipelines, and sports-specific calibrated OOS evaluation. Transferable ideas are adopted only when they preserve the repository's provenance and PIT contract.

Useful patterns include:

- rolling/walk-forward evaluation instead of random cross-validation;
- explicit leakage-audit records for decision/horizon pairs;
- purging/embargo when labels or rolling features can overlap evaluation windows;
- challenger calibration using Platt/isotonic-style methods only under an OOS guard;
- probability-first evaluation with log loss and Brier score in addition to accuracy;
- confidence/calibration reporting for practical interpretation;
- source/odds reconciliation without treating a single provider as ground truth.

## Autonomous work loop

For every improvement cycle:

1. inspect current production state and recent Actions;
2. search external public implementations for transferable engineering/statistical patterns;
3. identify the smallest change that can improve robustness or efficiency;
4. make the change reversible and narrowly scoped;
5. run syntax/invariant/PIT checks before considering it useful;
6. allow degraded sources to remain degraded rather than masking failure;
7. promote models only through the release gate;
8. verify the resulting Git commit and subsequent Actions before claiming completion.

## Rugby integration status

Rugby has an independent official-source coverage workflow and database. It must **not** be described as fully integrated into the canonical seven-sport research/model pipeline until its feature policy, PIT-safe outcome history, model training path, merge path, and release-gate treatment have all been verified. Coverage existence alone is not sufficient for model-production eligibility.

## Definition of done

The project is complete only when each production sport has:

- reliable historical and current data coverage for its intended competitions;
- explicit source provenance and PIT availability metadata;
- leakage-safe chronological OOS evaluation;
- calibrated probability outputs where the market supports them;
- frozen-holdout acceptance;
- incumbent/challenger promotion control;
- production invariants and fail-closed behavior;
- reproducible persisted artifacts and metrics;
- an operational path that can recover from transient source/network failures.

A successful GitHub Action is evidence that a run completed; it is **not by itself evidence that the model is accurate, calibrated, leakage-free, or production-ready**.
