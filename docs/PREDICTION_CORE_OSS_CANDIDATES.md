# Prediction-Core OSS Research Candidates

## Purpose

This is a research candidate database, not a dependency manifest. It narrows the broader 1000-item prediction-system OSS set to components that could add incremental predictive capability to the existing 7-Sport architecture.

Current active production scope remains VALORANT, Basketball, Volleyball, UFC and RIZIN.

## Why these candidates are prioritized

The repository already has substantial production orchestration, PIT controls, failure memory, experience learning, routing, calibration, uncertainty, monitoring and recovery. Therefore additional Agent/control-plane frameworks are lower priority than OSS that can improve:

- latent probabilistic state estimation
- leakage-safe optimization
- online adaptation and drift handling
- regime/change-point detection
- heterogeneous tabular modeling
- temporal trajectory modeling
- Bayesian diagnostics and uncertainty

## Adoption ladder

DISCOVERED → SOURCE_VERIFIED → LICENSE_CHECKED → SECURITY_CHECKED → LOCAL_REPRODUCTION → PIT_AUDIT → CHRONOLOGICAL_OOS/WFO → CALIBRATION → ROBUSTNESS → FROZEN_HOLDOUT → SHADOW → DECISION

No candidate in this registry is ADOPTED or PRODUCTION.

## Non-negotiable constraints

1. Candidate output cannot bypass prediction cutoff/PIT.
2. Retrieval time is not proof of historical availability.
3. Random temporal splits are not Production evidence.
4. Frozen holdout cannot be tuned.
5. Same-event snapshots remain a dependent event cluster.
6. External benchmark claims are Discovery, not Evidence.
7. TimesFM 3.0 default pretrained weights are explicitly restricted to non-commercial/non-production use; only permitted checkpoints/licenses may be evaluated.
8. Adding a candidate must not silently alter active sport scope or automatic model promotion.
9. New runtime dependencies are forbidden until a POC demonstrates incremental value and passes project release gates.
10. Unknown cost or billing risk remains HOLD.

## Current priority

**S+**: PyMC, Optuna, River, ruptures, CatBoost.

**S**: XGBoost.

**A**: StatsForecast, NeuralForecast, TimesFM, Darts, sktime, ArviZ.

The order is a research priority, not a claim of superiority. Adoption requires local evidence on this repository's chronological OOS/WFO and frozen holdout.
