# Research Best Practices Integrated into Production

This project prioritizes real-world robustness over backtest optimization. External public projects were reviewed for reusable engineering patterns; only patterns compatible with provenance-first, point-in-time (PIT), chronological OOS evaluation were adopted.

## Adopted principles

1. **Walk-forward OOS is the primary validation path.** Do not use random train/test splits for time-ordered sports data. Report fold-by-fold accuracy, log loss, and Brier score rather than relying on one aggregate score.
2. **Calibration is a release criterion.** Probability quality matters in addition to classification accuracy. Track ECE and Brier/log loss and reject unsafe probability models.
3. **Audit PIT before tuning.** Do not change weights, thresholds, or model complexity until the feature timestamp path and leakage audit are clean.
4. **Shift rolling features before aggregation.** Any rolling form/statistic must exclude the current event and all future events; conceptually, use `shift(1)` before rolling windows where the data representation requires it.
5. **Use stable entity identities.** Team/player identifiers must survive name changes, relocations, aliases, and historical naming differences without silently merging distinct entities.
6. **Treat source outages as coverage degradation, not permission to invent data.** Missing or unverifiable observations remain missing/rejected and must not be silently imputed from future information.
7. **Separate eligibility from probability.** A probability may exist mathematically while the event is still ineligible for production if PIT evidence, source availability, sample size, or model-quality gates fail.
8. **Prefer an incumbent-vs-candidate promotion test.** New features/models are promoted only when chronological OOS evidence supports them and safety gates remain satisfied.
9. **Automate experiments with reversible changes.** Research should be checkpointed, reproducible, and easy to compare/revert rather than accumulating untracked tuning changes.
10. **Optimize for production stability first.** Runtime improvements are allowed when they do not weaken data validation, PIT guarantees, calibration, or release gates.

## External references reviewed

- PuckAPI/claude-sports-analytics: walk-forward validation with fold-level probabilistic metrics.
- Christbey/picksports: explicit rule to prove PIT/calibration cleanliness before tuning.
- nurudeenaminu/PitchiQ_: temporal feature discipline, including excluding the current event from rolling features.
- WalrusQuant/sports-analytic-skills: model-card emphasis on stable identifiers and calibration when probabilities drive decisions.
- Kevinbeltran123/Betting-Platform: documented production failure modes around calibration and validation.
- davidpiontransactions-eng/pariscore: sport-specific PIT replay architecture for MMA data.
- eslazarev/purged-cross-validation: temporal leakage considerations for dependent observations.

## Non-adoption rules

Patterns are **not** copied merely because they appear in another repository. Randomized CV, future-data backfills, opaque scraped values, unverified market timestamps, arbitrary betting thresholds, or any method that can improve a historical score by violating PIT are explicitly excluded.

## Completion standard

A sport is not considered production-complete merely because its collector or GitHub Action is green. Completion requires source-backed events, valid timestamps, resolved historical outcomes where applicable, PIT-safe features, leakage audit success, chronological OOS evidence, calibrated probabilities, reproducible model metadata, and a passing release gate.
