# Sport-Specific OOS Adoption Protocol

Purpose: maximize real-world performance on unknown future data without increasing source count for its own sake.

## Independent sport lanes
Each sport is evaluated independently. No metric, source, feature, model, or promotion decision is transferred between sports without re-validation.

## Source admission order
1. Establish upstream independence. Mirrors, wrappers, republishers, and alternate APIs over the same underlying dataset do not count as independent.
2. Establish historical point-in-time availability. `retrieved_at_utc` is never evidence that the information existed before the prediction cutoff.
3. Preserve `source_available_at_utc`, `retrieved_at_utc`, URL, parser version, content hash, and source observation identifiers.
4. Validate schema, identity, duplicates, impossible values, timestamps, missingness, and outcome consistency.
5. Quantify genuinely new information relative to incumbent features.
6. Run chronological walk-forward OOS by competition/period where enough data exists.
7. Require replication on later periods and a frozen holdout.
8. Compare calibrated probability quality (LogLoss, Brier, Accuracy, ECE) and robustness, not only accuracy.
9. Prefer cheaper/free and operationally stable sources only after predictive value is established.
10. Adopt only when the challenger beats the incumbent under the production gate; otherwise keep the source as research-only.

## PIT-safe feature classes
Feature definitions must include an explicit effective timestamp and source observation IDs. Same-event statistics are prohibited unless the prediction is explicitly live/in-play and the observation timestamp is strictly before the prediction timestamp.

## OOS design
- Chronological split only.
- Walk-forward retraining with deterministic windows.
- Frozen final holdout never used for model selection or fitting.
- Preserve competition/gender/age/tier metadata; do not silently pool heterogeneous competitions.
- Report sample size and coverage alongside every metric.
- Do not accept one-off improvements that disappear on another period, tournament, or holdout.

## Teacher labels versus input features

Historical outcomes are labels for supervised learning. They become usable for later training state only after the source event has actually resolved under a conservative chronology rule. They are not treated as prediction-time feature observations. Any pre-event feature must independently satisfy available_at <= prediction_cutoff; retrieval time alone never proves historical availability.

## Calibration and robustness
Track probability calibration in addition to discrimination. Use reliability/ECE/Brier/LogLoss and inspect confidence under distribution shift. Monitor feature drift and prediction drift over time. A model that becomes overconfident under drift is not considered robust merely because its point accuracy remains acceptable.

## Failure semantics
- `READY`: all production gates pass.
- `BLOCKED`: a required safety, PIT, data-quality, calibration, reproducibility, or challenger gate fails; publish=false and the process exits non-zero.
- `DEFERRED`: data exists or collection is attempted but historical PIT/OOS evidence is insufficient; no production feature/model promotion is allowed. A DEFERRED state must be explicit in artifacts and logs.
- `REJECTED`: a source/feature/model is demonstrably unsuitable.

A green Action is never sufficient evidence of predictive quality. Conversely, a source outage must not be converted into fabricated observations merely to keep CI green.

## External-pattern inspirations
The protocol incorporates widely used production ML patterns: time-aware evaluation, leakage-aware feature lineage, drift/skew monitoring, probability calibration, champion/challenger comparison, reproducibility metadata, caching/checkpointing, and fail-closed release gates. These are engineering patterns, not evidence that a particular feature improves a given sport.

## Promotion record
Every adopted feature/source/model must record:
- sport
- source and upstream owner
- independence assessment
- license/terms status
- endpoint/dataset
- source availability evidence
- feature definition/version
- PIT audit result
- walk-forward OOS periods
- multi-period/competition replication
- frozen holdout metrics
- incumbent metrics
- calibration metrics
- missingness/drift observations
- cost/continuity assessment
- implementation commit
- Actions verification

No promotion is valid if any of the required evidence is missing.
