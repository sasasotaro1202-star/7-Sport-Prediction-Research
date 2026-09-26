# Nine-Sport Cross-Sport Data Layer

## Status

Research-only. No production model or production prediction artifact is changed by this layer.

The repository already uses sport-specific public/official collectors. This layer adds a registry for additional free/public enrichment candidates and a fail-closed PIT decision function.

## Cross-sport candidates

### SofaScore
Current public evidence shows broad multi-sport coverage and detailed match/fighter statistics. Public/third-party documentation also describes an undocumented API surface. It is therefore a research candidate, not an automatically trusted production source.

Useful potential enrichment includes event metadata, fixtures, participant/team information, match statistics, odds and, for MMA/boxing pages, fight statistics.

Historical availability is not assumed from retrieval time. A source snapshot must establish when a fact became observable before it can enter PIT-valid features.

### API-Sports
The provider currently advertises a free tier of 100 requests/day per API. Current official pages document basketball, volleyball, MMA, rugby and Formula 1 APIs among others. Coverage is endpoint/competition specific, so each sport/endpoint still requires its own data-quality and PIT validation.

A free key must never be silently introduced into the repository. Any future authenticated integration remains disabled unless credentials are explicitly supplied by the user.

### PandaScore
The current free tier provides schedules, results and context with a request limit. Historical/post-match detailed statistics are paid. It is therefore kept as a research candidate for prospective context, not treated as a free historical Opta substitute.

## PIT rule

- available_at <= prediction_time is eligible.
- available_at > prediction_time is a PIT failure.
- missing/unparseable available_at is UNKNOWN_FAIL_CLOSED.
- retrieval time is never substituted for historical availability evidence.
- candidate-source data cannot auto-promote a production model.

## Current production boundary

Existing sport-specific collectors remain the production/research data path. The new registry is a discovery and evaluation layer only.

Promotion requires the normal chronological OOS, leakage audit, calibration, frozen holdout and release-gate evidence already enforced by the repository.