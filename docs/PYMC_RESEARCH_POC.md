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
