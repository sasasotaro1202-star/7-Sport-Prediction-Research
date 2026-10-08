# PyMC Research POC

This is the first Prediction-Core OSS POC from the external candidate registry.

## Scope

The POC tests only the mechanical feasibility of a hierarchical Bayesian event model:
- chronological synthetic event split
- team-level partial pooling
- posterior probability generation
- basic posterior diagnostics
- LogLoss/Brier/Accuracy against a trivial 0.5 baseline

It does not establish a 7-Sport performance improvement.

## PIT boundary

Synthetic covariates are created before their corresponding outcome. The script records an event-relative prediction cutoff and explicitly asserts that no post-outcome feature is introduced.

No 7-Sport production database, historical prediction artifact, holdout artifact, or model registry is consumed.

## Fixed software input

The research workflow installs pymc==6.3.2 only inside the isolated POC job. The production requirements.txt is intentionally unchanged.

PyMC is distributed under Apache-2.0; the verified repository LICENSE states this explicitly.

## Promotion boundary

Status remains IMPLEMENTED / RESEARCH-ONLY / UNVERIFIED.

The next stage is real 7-Sport PIT-safe local reproduction, followed by chronological OOS/WFO, calibration, robustness, frozen holdout and shadow evaluation. No automatic promotion is allowed.


## PIT shadow pipeline hardening — 2026-10-08

The real-event shadow path is research-only and does not modify production models.

The pipeline now:
1. restores existing verified sport-scoped DB caches;
2. forces a strict PIT replay rebuild per active sport;
3. requires verified A/B outcomes, replayable CLEAN/PASS rows, CLEAN/PASS features and EXACT source availability before the cutoff;
4. merges only READY active-sport partitions;
5. rejects merged event data containing non-active sports;
6. persists explicit source-manifest and execution-boundary artifacts;
7. saves a reusable `trajectory-ready-db-v1-merged-<run_id>` cache only after the full five-sport dataset is READY.

An observed execution of the first implementation failed before PIT replay because `pit_replay_builder` imported the full ML training module and the isolated workflow did not install its dependencies. This was repaired by moving the immutable `POLICY`/sport registry to `src/research_policy.py` and making the PIT builder depend only on that lightweight policy module.

A subsequent execution then exposed a contract-test reference error, which was corrected so the test checks `src/pit_replay_builder.py` and `src/research_cycle_v4.py` directly.

Latest status at documentation time:
- PyMC synthetic POC: EXECUTED / VERIFIED
- PyMC 7-Sport predictive performance: UNVERIFIED
- Real-event PIT Shadow Dataset: UNVERIFIABLE on the latest HEAD until a fresh post-fix Actions run completes
- PyMC Production Adoption: HOLD
